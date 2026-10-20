"""The SDK hooks that gate tool calls: command approvals and the stop button.

Every coding agent tool call goes through the `PreToolUse` hook that
`gate_tool_calls` builds for a run. It decides each call:

- `allow` — run it.
- `deny` — skip it and tell the model why, like after the stop button.
- `defer` — end the run here, leaving the call waiting. A `run_command` that
  `command_needs_approval()` defers, and `agent/turns.py` posts Approve / Deny
  buttons. Resuming the session asks the hook about the same call again, and
  the decision is the answer.
- `ask` — hand the call to `answer_unanswered`. That's only for a call a dropped
  paused run left waiting.
"""

from logging import getLogger

from claude_agent_sdk import (
    HookCallback,
    HookContext,
    HookInput,
    HookJSONOutput,
    PermissionResultDeny,
    ToolPermissionContext,
)

from agent.approvals import command_needs_approval
from agent.runtime import current_deps

logger = getLogger(__name__)

# The name the model calls `run_command` by, through the agent's MCP server.
RUN_COMMAND = "mcp__coding-agent__run_command"


def _decide(decision: str, reason: str | None = None) -> HookJSONOutput:
    output = {"hookEventName": "PreToolUse", "permissionDecision": decision}
    if reason:
        output["permissionDecisionReason"] = reason
    return {"hookSpecificOutput": output}


def gate_tool_calls(
    *, approval: tuple[str, bool] | None = None, unanswered: str | None = None
) -> HookCallback:
    """The `PreToolUse` hook for one coding agent run.

    Args:
        approval: The deferred call this run resumes, and whether someone approved it.
        unanswered: A call a paused run left waiting that was never resumed.
    """

    async def hook(
        input_data: HookInput, tool_use_id: str | None, _context: HookContext
    ) -> HookJSONOutput:
        # Resuming the session asks about a call left waiting before anything else.
        if tool_use_id == unanswered:
            return _decide("ask")
        # Skip every tool call once someone presses the stop button, so a
        # stopped turn changes nothing more in the repo or the channel while
        # the model wraps up.
        if current_deps.get().session.stopped:
            return _decide(
                "deny",
                "The user stopped this session. Don't call any more tools. "
                "Reply with one short line saying you've stopped.",
            )
        if approval is not None and tool_use_id == approval[0]:
            if approval[1]:
                return _decide("allow")
            return _decide("deny", "The user denied running this command.")
        if input_data["tool_name"] == RUN_COMMAND:
            command = input_data["tool_input"].get("command", "")
            if command_needs_approval(command):
                logger.info("run_command needs approval: %s", command)
                return _decide("defer")
        return _decide("allow")

    return hook


async def answer_unanswered(
    _tool_name: str, _tool_input: dict, _context: ToolPermissionContext
) -> PermissionResultDeny:
    """Answer the call a dropped paused run left waiting, as not run.

    This is the SDK's `can_use_tool` callback, and the hook only sends it that
    call. Interrupting ends the old turn there, without a reply from the model,
    so the new turn starts right after.
    """
    return PermissionResultDeny(
        message="Not run. The user didn't approve this command.", interrupt=True
    )
