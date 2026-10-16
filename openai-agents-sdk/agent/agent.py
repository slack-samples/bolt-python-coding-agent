"""The OpenAI Agents SDK side of the coding agent.

Everything that touches the SDK lives here, in `agent/guardrails.py`, and in
`agent/tools/`. The turn handling in `agent/turns.py` calls only `run_request`,
which returns the reply text, and `start_run` and `resume_run`, which return a
`RunOutcome`.
"""

import json
from dataclasses import dataclass

from agents import (
    Agent,
    FunctionToolResult,
    ModelSettings,
    RunContextWrapper,
    RunErrorHandlerInput,
    RunErrorHandlerResult,
    Runner,
    RunState,
    ToolApprovalItem,
    ToolsToFinalOutputResult,
)

from agent.outcome import RunOutcome
from agent.prompts import REQUEST_PROMPT, SYSTEM_PROMPT
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
# so this is well above the SDK's default of 10.
MAX_TURNS = 50

# Drop the oldest conversation when a long session outgrows the model's
# context window, rather than failing every turn after that.
MODEL_SETTINGS = ModelSettings(truncation="auto")


def _stop_once_channel_created(
    wrapper: RunContextWrapper[RequestDeps], _results: list[FunctionToolResult]
) -> ToolsToFinalOutputResult:
    """End the request once a code channel exists, since the work continues there."""
    return ToolsToFinalOutputResult(
        is_final_output=wrapper.context.code_channel_id is not None,
        final_output=None,
    )


def _stop_once_archived(
    wrapper: RunContextWrapper[AgentDeps], _results: list[FunctionToolResult]
) -> ToolsToFinalOutputResult:
    """End the turn once the channel is archived, since nothing more can be posted."""
    return ToolsToFinalOutputResult(
        is_final_output=wrapper.context.session.archived,
        final_output=None,
    )


request_agent = Agent[RequestDeps](
    name="Coding Agent",
    instructions=REQUEST_PROMPT,
    tools=[create_code_channel],
    tool_use_behavior=_stop_once_channel_created,
    model="gpt-6-luna",
    model_settings=MODEL_SETTINGS,
)

agent = Agent[AgentDeps](
    name="Coding Agent",
    instructions=SYSTEM_PROMPT,
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
    tool_use_behavior=_stop_once_archived,
    model="gpt-6.1-sol",
    model_settings=MODEL_SETTINGS,
)


@dataclass
class PausedRun:
    """The SDK's handle on a run paused for approval, passed back to `resume_run`."""

    state: RunState
    item: ToolApprovalItem


def _settle(result) -> RunOutcome:
    """Turn a RunResult into a RunOutcome, detecting a pending approval."""
    history = result.to_input_list()
    state = result.to_state()
    interruptions = state.get_interruptions()
    if interruptions:
        # The history ends with calls still waiting on approval. Give each one
        # an output so the history stays valid if the run is stopped or replaced
        # instead of resumed. A resumed run replaces this history with its own.
        history += [
            {
                "type": "function_call_output",
                "call_id": item.call_id,
                "output": "Not run. The user didn't approve this command.",
            }
            for item in interruptions
        ]
        # One command at a time keeps the sample's approval UX simple.
        item = interruptions[0]
        # The SDK gives the tool call's arguments as a JSON string.
        arguments = json.loads(item.arguments or "{}")
        return RunOutcome(
            paused=PausedRun(state=state, item=item),
            command=arguments.get("command", ""),
            history=history,
        )
    return RunOutcome(final_output=result.final_output, history=history)


def _out_of_turns(_data: RunErrorHandlerInput) -> RunErrorHandlerResult:
    """End a turn that used every model call with a message, keeping its history."""
    return RunErrorHandlerResult(
        final_output=(
            f"I used all {MAX_TURNS} steps I get in one turn before finishing. "
            "Send a message and I'll pick up where I left off."
        ),
    )


async def run_request(prompt: str, deps: RequestDeps) -> str | None:
    """Reply to a request outside a code channel, or create one for it via the tool."""
    result = await Runner.run(request_agent, input=prompt, context=deps)
    return result.final_output


async def start_run(history: list, text: str, deps: AgentDeps) -> RunOutcome:
    """Start an agent turn. May complete, or pause awaiting command approval."""
    result = await Runner.run(
        agent,
        input=history + [{"role": "user", "content": text}],
        context=deps,
        max_turns=MAX_TURNS,
        error_handlers={"max_turns": _out_of_turns},
    )
    return _settle(result)


async def resume_run(paused: PausedRun, approved: bool, deps: AgentDeps) -> RunOutcome:
    """Resume a paused run with the user's decision on its pending command."""
    if approved:
        paused.state.approve(paused.item)
    else:
        paused.state.reject(
            paused.item,
            rejection_message="The user denied running this command.",
        )
    # The paused state carries the run's turn count and MAX_TURNS with it.
    result = await Runner.run(
        agent,
        paused.state,
        context=deps,
        error_handlers={"max_turns": _out_of_turns},
    )
    return _settle(result)
