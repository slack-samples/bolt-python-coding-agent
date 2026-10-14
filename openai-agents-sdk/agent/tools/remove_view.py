from agents import function_tool
from agents.run_context import RunContextWrapper
from slack_sdk.errors import SlackApiError

from agent.deps import AgentDeps
from agent.guardrails import session_stopped


@function_tool(tool_input_guardrails=[session_stopped])
async def remove_view(wrapper: RunContextWrapper[AgentDeps], view_id: str) -> str:
    """Remove a view tab from the code channel.

    Use it to clear out a view that's stale or no longer useful. Find the
    `view_id` with `list_views` first.

    Args:
        view_id: The view_id of the tab to remove, as returned by `list_views`.
    """
    deps = wrapper.context
    try:
        await deps.client.agents_conversations_removeView(
            channel_id=deps.channel_id,
            view_id=view_id,
        )
        return f"Removed view {view_id}."
    except SlackApiError as e:
        return f"Could not remove the view: {e.response['error']}"
