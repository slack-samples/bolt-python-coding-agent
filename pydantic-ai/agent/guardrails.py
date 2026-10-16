"""The hooks around the coding agent's tool calls: command approvals, the stop button, and tool errors."""

from logging import getLogger

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.capabilities import Hooks
from pydantic_ai.exceptions import ApprovalRequired, SkipToolExecution, ToolFailed

from agent.approvals import command_needs_approval
from agent.sessions import AgentDeps

logger = getLogger(__name__)

STOPPED = (
    "The user stopped this session. Don't call any more tools. "
    "Reply with one short line saying you've stopped."
)

guardrails = Hooks[AgentDeps]()


@guardrails.on.before_tool_execute
async def session_stopped(ctx: RunContext[AgentDeps], *, call, tool_def, args):
    """Skip every tool call once someone presses the stop button.

    The coding agent lists these hooks, so a stopped turn changes nothing more in
    the repo or the channel while the model wraps up.
    """
    if ctx.deps.session.stopped:
        raise SkipToolExecution(STOPPED)
    return args


@guardrails.on.before_output_process
async def session_stopped_output(ctx: RunContext[AgentDeps], *, output_context, output):
    """Skip `archive_channel` too once the session is stopped.

    It ends the turn as the agent's output rather than running as a tool, so it
    goes through this hook instead of `session_stopped`.
    """
    if ctx.deps.session.stopped and output_context.tool_call is not None:
        raise ModelRetry(STOPPED)
    return output


@guardrails.on.before_tool_execute(tools=["run_command"])
async def run_command_needs_approval(
    ctx: RunContext[AgentDeps], *, call, tool_def, args
):
    """Pause the run on a command that needs approval, before it runs.

    Raising ApprovalRequired ends the run with DeferredToolRequests, which
    `agent/turns.py` posts as Approve / Deny buttons. An approved call runs this
    again with `ctx.tool_call_approved` set.
    """
    command = args.get("command", "")
    if not ctx.tool_call_approved and command_needs_approval(command):
        logger.info("run_command needs approval: %s", command)
        raise ApprovalRequired()
    return args


@guardrails.on.tool_execute_error
async def tool_failed(ctx: RunContext[AgentDeps], *, call, tool_def, args, error):
    """Tell the model a tool failed, so the turn carries on instead of failing."""
    logger.error("Tool %s failed", call.tool_name, exc_info=error)
    raise ToolFailed("An error occurred while running the tool. Please try again.")
