from claude_agent_sdk import tool
from slack_sdk.errors import SlackApiError

from agent.runtime import current_deps, tool_result

DESCRIPTION = """\
Set the items pinned to the context bar at the top of the code channel.

Use it to show where the work stands: the repo, branch, PR, and CI status. \
The list replaces the current set, so always send every item you want to \
keep. Keep labels current as things change. At most 5 items.\
"""

CONTEXT_BAR_ITEM = {
    "type": "object",
    "properties": {
        "key": {
            "type": "string",
            "description": "A unique key for the item, such as `repo`, `branch`, `pr`, or `ci`.",
        },
        "label": {
            "type": "string",
            "description": "The display text, such as `PR #42 is open` or `Tests passing`.",
        },
        "icon": {
            "type": "string",
            "enum": [
                "branch",
                "folder",
                "hierarchy",
                "life-ring",
                "link",
                "globe",
                "terminal",
                "code",
                "search",
                "lock",
            ],
            "description": "An icon shown beside the label.",
        },
        "url": {
            "type": "string",
            "description": "Makes the item a link to this URL.",
        },
    },
    "required": ["key", "label"],
}


@tool(
    "set_context_bar",
    DESCRIPTION,
    {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": CONTEXT_BAR_ITEM,
                "description": "The full set of context bar items, in display order.",
            },
        },
        "required": ["items"],
    },
)
async def set_context_bar(args: dict) -> dict:
    items = args["items"]
    deps = current_deps.get()
    try:
        await deps.client.agents_conversations_setProperties(
            channel_id=deps.channel_id,
            code_channel={"context_bar_items": items[:5]},
        )
        return tool_result(f"Set {min(len(items), 5)} context bar items.")
    except SlackApiError as e:
        return tool_result(f"Could not set the context bar: {e.response['error']}")
