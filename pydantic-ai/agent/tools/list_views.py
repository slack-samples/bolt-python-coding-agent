from pydantic_ai import RunContext
from slack_sdk.errors import SlackApiError

from agent.sessions import AgentDeps


async def list_views(ctx: RunContext[AgentDeps]) -> str:
    """List the view tabs currently attached to the code channel.

    Use it before publishing a new view, since a channel holds at most 5, or to
    find the `view_id` of a tab to remove.
    """
    deps = ctx.deps
    try:
        response = await deps.client.agents_conversations_listViews(
            channel_id=deps.channel_id,
        )
    except SlackApiError as e:
        return f"Could not list views: {e.response['error']}"

    views = response.get("views", [])
    if not views:
        return "No views are attached to this channel yet."
    lines = [
        f"- {v.get('name') or v.get('label')}: view_key={v.get('view_key', '(diff)')} "
        f"view_id={v['view_id']} version={v.get('content_version')}"
        for v in views
    ]
    return f"{len(views)} of 5 views attached:\n" + "\n".join(lines)
