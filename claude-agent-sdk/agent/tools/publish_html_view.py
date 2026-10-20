from claude_agent_sdk import tool
from slack_sdk.errors import SlackApiError

from agent.sessions import current_deps
from agent.tools import tool_result

DESCRIPTION = """\
Publish an HTML document as a tab in the code channel.

Use it for rich output that reads better rendered than as a message, such as \
a test report or coverage summary. Calling it again with the same `view_key` \
updates that tab in place. A channel holds at most 5 views.\
"""


@tool(
    "publish_html_view",
    DESCRIPTION,
    {
        "type": "object",
        "properties": {
            "view_key": {
                "type": "string",
                "description": "A stable key for this view, such as `reports/tests.html`.",
            },
            "name": {
                "type": "string",
                "description": "The short tab label shown in the channel, such as `Tests`.",
            },
            "html": {
                "type": "string",
                "description": "A full, self-contained HTML document with inline styles and no external scripts.",
            },
        },
        "required": ["view_key", "name", "html"],
    },
)
async def publish_html_view(args: dict) -> dict:
    deps = current_deps.get()
    try:
        response = await deps.client.agents_conversations_setView(
            channel_id=deps.channel_id,
            type="html",
            view_key=args["view_key"],
            name=args["name"],
            content=args["html"],
        )
        return tool_result(
            f"Published the `{args['name']}` tab (view_id {response['view_id']})."
        )
    except SlackApiError as e:
        return tool_result(f"Could not publish the view: {e.response['error']}")
