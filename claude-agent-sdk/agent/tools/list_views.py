from claude_agent_sdk import tool
from slack_sdk.errors import SlackApiError

from agent.sessions import current_deps
from agent.tools import tool_result

DESCRIPTION = """\
List the view tabs currently attached to the code channel.

Use it before publishing a new view, since a channel holds at most 5, or to \
find the `view_id` of a tab to remove.\
"""


@tool("list_views", DESCRIPTION, {"type": "object", "properties": {}})
async def list_views(_args: dict) -> dict:
    deps = current_deps.get()
    try:
        response = await deps.client.agents_conversations_listViews(
            channel_id=deps.channel_id,
        )
    except SlackApiError as e:
        return tool_result(f"Could not list views: {e.response['error']}")

    views = response.get("views", [])
    if not views:
        return tool_result("No views are attached to this channel yet.")
    lines = [
        f"- {v.get('name') or v.get('label')}: view_key={v.get('view_key', '(diff)')} "
        f"view_id={v['view_id']} version={v.get('content_version')}"
        for v in views
    ]
    return tool_result(f"{len(views)} of 5 views attached:\n" + "\n".join(lines))
