from pydantic_ai import RunContext
from slack_sdk.errors import SlackApiError

from agent.sessions import AgentDeps


async def rename_session(ctx: RunContext[AgentDeps], title: str) -> str:
    """Rename the code channel and its session title.

    Use it when the task's focus changes enough that the current name would
    mislead someone scanning their channels.

    Args:
        title: A short, descriptive title for the task, such as `Fix flaky login test`.
    """
    deps = ctx.deps
    try:
        await deps.client.agents_sessions_rename(
            channel_id=deps.channel_id, title=title
        )
        return f"Renamed the session to {title!r}."
    except SlackApiError as e:
        return f"Could not rename the session: {e.response['error']}"
