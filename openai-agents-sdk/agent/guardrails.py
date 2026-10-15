"""The SDK hooks that gate tool calls: command approvals and the stop button."""

from logging import getLogger

from agents import (
    ToolGuardrailFunctionOutput,
    ToolInputGuardrailData,
    tool_input_guardrail,
)

from agent.approvals import command_needs_approval

logger = getLogger(__name__)


async def run_command_needs_approval(_ctx, arguments: dict, _call_id: str) -> bool:
    """The `needs_approval` hook for `run_command`, checked with its arguments before it runs.

    Returning True pauses the run with a ToolApprovalItem the listener handles.
    """
    command = (arguments or {}).get("command", "")
    needs = command_needs_approval(command)
    if needs:
        logger.info("run_command needs approval: %s", command)
    return needs


@tool_input_guardrail
def session_stopped(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
    """Skip every tool call once someone presses the stop button.

    Each code channel tool lists this guardrail, so a stopped turn changes nothing
    more in the repo or the channel while the model wraps up.
    """
    if data.context.context.session.stopped:
        return ToolGuardrailFunctionOutput.reject_content(
            "The user stopped this session. Don't call any more tools. "
            "Reply with one short line saying you've stopped."
        )
    return ToolGuardrailFunctionOutput.allow()
