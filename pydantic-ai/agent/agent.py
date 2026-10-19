"""The Pydantic AI side of the coding agent.

Everything that touches Pydantic AI lives here, in `agent/guardrails.py`, and in
`agent/tools/`. The turn handling in `agent/turns.py` calls only `run_request`,
which returns the reply text, and `start_run` and `resume_run`, which return a
`RunOutcome`.
"""

import os
from dataclasses import dataclass

from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    ToolDenied,
    ToolOutput,
    UsageLimits,
)
from pydantic_ai.capabilities import SelectModel
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
)
from pydantic_ai.models.anthropic import AnthropicCompaction
from pydantic_ai.models.openai import OpenAICompaction
from pydantic_ai.usage import RunUsage

from agent.guardrails import guardrails
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

# Model requests allowed per turn. Coding work reads several files before
# editing, so this is well above what a quick answer needs.
MAX_TURNS = 50

# The answer for a command that was never resumed, so the history stays valid.
NOT_APPROVED = "Not run. The user didn't approve this command."


def select_model(*, anthropic: str, openai: str) -> SelectModel:
    """Pick the model when a run starts, by which API key is set.

    Prefers Anthropic when both keys are set. Picking at run time, not on the
    agent, means no model client is created at import.
    """

    def selector(_ctx) -> str:
        if os.environ.get("ANTHROPIC_API_KEY"):
            return f"anthropic:{anthropic}"
        if os.environ.get("OPENAI_API_KEY"):
            return f"openai:{openai}"
        raise RuntimeError(
            "No AI provider configured. "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY in your environment."
        )

    return SelectModel(selector)


request_agent = Agent(
    deps_type=RequestDeps,
    instructions=REQUEST_PROMPT,
    # Creating a code channel ends the request as its output, since the work
    # continues there.
    output_type=[ToolOutput(create_code_channel, name="create_code_channel"), str],
    capabilities=[select_model(anthropic="claude-haiku-4-5", openai="gpt-6-luna")],
)

agent = Agent(
    deps_type=AgentDeps,
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
    ],
    # Archiving the channel ends the turn as its output, since nothing more can
    # be posted. A command waiting on approval ends it with DeferredToolRequests.
    output_type=[
        ToolOutput(archive_channel, name="archive_channel"),
        str,
        DeferredToolRequests,
    ],
    capabilities=[
        select_model(anthropic="claude-sonnet-5-5", openai="gpt-6.1-sol"),
        guardrails,
        # Compact the oldest conversation when a long session outgrows the
        # model's context window, rather than failing every turn after that.
        # Each one only applies to its own provider's models.
        AnthropicCompaction(),
        OpenAICompaction(),
    ],
)


@dataclass
class PausedRun:
    """A run paused for approval, passed back to `resume_run`."""

    # The conversation up to the calls waiting on approval.
    messages: list[ModelMessage]
    requests: DeferredToolRequests
    # The model requests this turn used, so a resumed run keeps counting them.
    usage: RunUsage


def _settle(result, deps: AgentDeps) -> RunOutcome:
    """Turn a run result into a RunOutcome, detecting a pending approval."""
    history = result.all_messages()
    if deps.session.archived:
        return RunOutcome(history=history)
    if not isinstance(result.output, DeferredToolRequests):
        return RunOutcome(final_output=result.output, history=history)

    requests = result.output
    # The history ends with calls still waiting on approval. Give each one a
    # return so the history stays valid if the run is stopped or replaced
    # instead of resumed. A resumed run replaces this history with its own.
    answered = ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name=call.tool_name,
                content=NOT_APPROVED,
                tool_call_id=call.tool_call_id,
            )
            for call in requests.approvals
        ]
    )
    # One command at a time keeps the sample's approval UX simple.
    call = requests.approvals[0]
    return RunOutcome(
        paused=PausedRun(messages=history, requests=requests, usage=result.usage),
        command=call.args_as_dict().get("command", ""),
        history=[*history, answered],
    )


def _out_of_turns(messages: list[ModelMessage]) -> RunOutcome:
    """End a turn that used every model request with a message, keeping its history."""
    text = (
        f"I used all {MAX_TURNS} steps I get in one turn before finishing. "
        "Send a message and I'll pick up where I left off."
    )
    return RunOutcome(
        final_output=text,
        history=[*messages, ModelResponse(parts=[TextPart(content=text)])],
    )


async def _run(deps: AgentDeps, **run_args) -> RunOutcome:
    """Run the coding agent until it finishes, pauses on an approval, or runs out of turns."""
    async with agent.iter(
        deps=deps,
        usage_limits=UsageLimits(request_limit=MAX_TURNS),
        **run_args,
    ) as run:
        try:
            async for _node in run:
                pass
        except UsageLimitExceeded:
            return _out_of_turns(run.all_messages())
    return _settle(run.result, deps)


async def run_request(prompt: str, deps: RequestDeps) -> str | None:
    """Reply to a request outside a code channel, or create one for it via the tool."""
    result = await request_agent.run(prompt, deps=deps)
    # Once the channel exists, the output is the tool's result, not a reply.
    return None if deps.code_channel_id else result.output


async def start_run(history: list, text: str, deps: AgentDeps) -> RunOutcome:
    """Start an agent turn. May complete, or pause awaiting command approval."""
    return await _run(deps, user_prompt=text, message_history=history)


async def resume_run(paused: PausedRun, approved: bool, deps: AgentDeps) -> RunOutcome:
    """Resume a paused run with the user's decision on its pending command."""
    first, *rest = paused.requests.approvals
    decision = True if approved else ToolDenied("The user denied running this command.")
    # Every pending call needs an answer, so any other command from the same
    # step is answered as not run, and the model can ask for it again.
    approvals = {
        first.tool_call_id: decision,
        **{call.tool_call_id: ToolDenied(NOT_APPROVED) for call in rest},
    }
    return await _run(
        deps,
        message_history=paused.messages,
        deferred_tool_results=paused.requests.build_results(approvals=approvals),
        usage=paused.usage,
    )
