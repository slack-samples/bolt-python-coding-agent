"""The Claude Agent SDK side of the coding agent.

Everything that touches the SDK lives here, in `agent/guardrails.py`, and in
`agent/tools/`. The turn handling in `agent/turns.py` calls only `run_request`,
which returns the reply text, and `start_run` and `resume_run`, which return a
`RunOutcome`.
"""

from dataclasses import dataclass

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
    ResultMessage,
    create_sdk_mcp_server,
)

from agent.guardrails import answer_unanswered, gate_tool_calls
from agent.outcome import RunOutcome
from agent.prompts import REQUEST_PROMPT, SYSTEM_PROMPT
from agent.runtime import current_deps
from agent.sessions import AgentDeps, RequestDeps
from agent.tools import (
    archive_channel,
    clone_repo,
    create_code_channel,
    edit_file,
    list_views,
    publish_diff,
    publish_html_view,
    read_file,
    read_plan,
    remove_view,
    rename_session,
    run_command,
    set_commands,
    set_context_bar,
    write_file,
    write_plan,
)

# Model calls allowed per turn. Coding work reads several files before editing,
# so this leaves plenty of room.
MAX_TURNS = 50

# The tools each agent can call, served in-process. The model sees each one as
# `mcp__coding-agent__<name>`.
request_tools = create_sdk_mcp_server(name="coding-agent", tools=[create_code_channel])
tools = create_sdk_mcp_server(
    name="coding-agent",
    tools=[
        clone_repo,
        read_file,
        write_file,
        edit_file,
        run_command,
        publish_diff,
        set_context_bar,
        write_plan,
        read_plan,
        publish_html_view,
        list_views,
        remove_view,
        set_commands,
        rename_session,
        archive_channel,
    ],
)

# A turn that ended by interrupting, which only closing out a dropped pause does.
INTERRUPTED = ("aborted_streaming", "aborted_tools")


async def _stop_once_channel_created(
    _input: HookInput, _tool_use_id: str | None, _context: HookContext
) -> HookJSONOutput:
    """End the request once a code channel exists, since the work continues there."""
    if current_deps.get().code_channel_id is not None:
        return {"continue_": False}
    return {}


async def _stop_once_archived(
    _input: HookInput, _tool_use_id: str | None, _context: HookContext
) -> HookJSONOutput:
    """End the turn once the channel is archived, since nothing more can be posted."""
    if current_deps.get().session.archived:
        return {"continue_": False}
    return {}


def _request_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model="claude-haiku-4-5",
        system_prompt=REQUEST_PROMPT,
        mcp_servers={"coding-agent": request_tools},
        allowed_tools=["mcp__coding-agent__create_code_channel"],
        hooks={"PostToolUse": [HookMatcher(hooks=[_stop_once_channel_created])]},
        # Only the tools above, and none of the settings, CLAUDE.md files, or
        # MCP servers configured on this machine.
        tools=[],
        setting_sources=[],
        strict_mcp_config=True,
        # The prompt quotes Slack messages, so an `@path` in one can't read a local file.
        verbatim_prompts=True,
    )


def _options(
    history: list,
    *,
    approval: tuple[str, bool] | None = None,
    unanswered: str | None = None,
) -> ClaudeAgentOptions:
    """Options for a coding agent run that continues the session in `history`, if any."""
    return ClaudeAgentOptions(
        model="claude-sonnet-5-5",
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"coding-agent": tools},
        hooks={
            "PreToolUse": [
                HookMatcher(
                    hooks=[gate_tool_calls(approval=approval, unanswered=unanswered)]
                )
            ],
            "PostToolUse": [HookMatcher(hooks=[_stop_once_archived])],
        },
        can_use_tool=answer_unanswered,
        max_turns=MAX_TURNS,
        resume=history[-1].session_id if history else None,
        tools=[],
        setting_sources=[],
        strict_mcp_config=True,
        verbatim_prompts=True,
    )


async def _run(
    options: ClaudeAgentOptions,
    deps: AgentDeps | RequestDeps,
    prompt: str | None,
) -> ResultMessage:
    """Run the agent once and return its result.

    Without a prompt, the run resumes the session's deferred command. The tools
    and hooks read `deps` from `current_deps`, set before the client starts so
    its tasks see it.
    """
    current_deps.set(deps)
    async with ClaudeSDKClient(options) as client:
        if prompt is not None:
            await client.query(prompt)
        async for message in client.receive_messages():
            if not isinstance(message, ResultMessage):
                continue
            # Closing out a dropped pause ends that old turn first, with its own result.
            if message.terminal_reason in INTERRUPTED:
                continue
            return message
    raise RuntimeError("The agent stopped without a result.")


@dataclass
class PausedRun:
    """A run that ended on a deferred `run_command`, picked back up by resuming its session.

    `history` ends with that run's result, whose `deferred_tool_use` is the
    command waiting on approval.
    """

    history: list[ResultMessage]


def _settle(history: list, result: ResultMessage) -> RunOutcome:
    """Turn a run's result into a RunOutcome, detecting a pending approval.

    The conversation itself lives in the Claude Code session, so `history` is
    the session's results. The last one says which session to resume, and any
    command it left waiting.
    """
    history = [*history, result]
    if result.deferred_tool_use is not None:
        # If this run is stopped or replaced instead of resumed, the next run
        # answers this call as not run, so the session stays valid either way.
        return RunOutcome(
            paused=PausedRun(history=history),
            command=result.deferred_tool_use.input.get("command", ""),
            history=history,
        )
    if result.subtype == "error_max_turns":
        return RunOutcome(
            final_output=(
                f"I used all {MAX_TURNS} steps I get in one turn before finishing. "
                "Send a message and I'll pick up where I left off."
            ),
            history=history,
        )
    if result.is_error:
        raise RuntimeError("; ".join(result.errors or []) or result.result)
    return RunOutcome(final_output=result.result, history=history)


async def run_request(prompt: str, deps: RequestDeps) -> str | None:
    """Reply to a request outside a code channel, or create one for it via the tool."""
    result = await _run(_request_options(), deps, prompt)
    if result.is_error:
        raise RuntimeError("; ".join(result.errors or []) or result.result)
    return result.result


async def start_run(history: list, text: str, deps: AgentDeps) -> RunOutcome:
    """Start an agent turn. May complete, or pause awaiting command approval."""
    # A paused run that was stopped or replaced left its command waiting.
    waiting = history[-1].deferred_tool_use if history else None
    options = _options(history, unanswered=waiting.id if waiting else None)
    result = await _run(options, deps, text)
    return _settle(history, result)


async def resume_run(paused: PausedRun, approved: bool, deps: AgentDeps) -> RunOutcome:
    """Resume a paused run with the user's decision on its pending command."""
    waiting = paused.history[-1].deferred_tool_use
    options = _options(paused.history, approval=(waiting.id, approved))
    result = await _run(options, deps, None)
    return _settle(paused.history, result)
