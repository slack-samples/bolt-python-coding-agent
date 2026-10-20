from claude_agent_sdk import tool
from slack_sdk.errors import SlackApiError

from agent.sessions import current_deps
from agent.tools import tool_result

DESCRIPTION = """\
Remove a view tab from the code channel.

Use it to clear out a view that's stale or no longer useful. Find the \
`view_id` with `list_views` first.\
"""


@tool(
    "remove_view",
    DESCRIPTION,
    {
        "type": "object",
        "properties": {
            "view_id": {
                "type": "string",
                "description": "The view_id of the tab to remove, as returned by `list_views`.",
            },
        },
        "required": ["view_id"],
    },
)
async def remove_view(args: dict) -> dict:
    deps = current_deps.get()
    try:
        await deps.client.agents_conversations_removeView(
            channel_id=deps.channel_id,
            view_id=args["view_id"],
        )
        return tool_result(f"Removed view {args['view_id']}.")
    except SlackApiError as e:
        return tool_result(f"Could not remove the view: {e.response['error']}")
