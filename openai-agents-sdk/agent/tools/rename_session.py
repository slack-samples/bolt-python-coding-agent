from agents import function_tool
from agents.run_context import RunContextWrapper
from slack_sdk.errors import SlackApiError

from agent.guardrails import session_stopped
from agent.sessions import AgentDeps


@function_tool(tool_input_guardrails=[session_stopped])
async def rename_session(wrapper: RunContextWrapper[AgentDeps], title: str) -> str:
    """Rename the code channel and its session title.

    Use it when the task's focus changes enough that the current name would
    mislead someone scanning their channels.

    Args:
        title: A short, descriptive title for the task, such as `Fix flaky login test`.
    """
    deps = wrapper.context
    try:
        await deps.client.agents_sessions_rename(
            channel_id=deps.channel_id, title=title
        )
        return f"Renamed the session to {title!r}."
    except SlackApiError as e:
        return f"Could not rename the session: {e.response['error']}"
