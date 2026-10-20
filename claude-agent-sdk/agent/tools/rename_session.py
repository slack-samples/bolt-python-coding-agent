from claude_agent_sdk import tool
from slack_sdk.errors import SlackApiError

from agent.sessions import current_deps
from agent.tools import tool_result

DESCRIPTION = """\
Rename the code channel and its session title.

Use it when the task's focus changes enough that the current name would \
mislead someone scanning their channels.\
"""


@tool(
    "rename_session",
    DESCRIPTION,
    {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "A short, descriptive title for the task, such as `Fix flaky login test`.",
            },
        },
        "required": ["title"],
    },
)
async def rename_session(args: dict) -> dict:
    deps = current_deps.get()
    try:
        await deps.client.agents_sessions_rename(
            channel_id=deps.channel_id, title=args["title"]
        )
        return tool_result(f"Renamed the session to {args['title']!r}.")
    except SlackApiError as e:
        return tool_result(f"Could not rename the session: {e.response['error']}")
