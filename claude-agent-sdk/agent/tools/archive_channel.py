from claude_agent_sdk import tool
from slack_sdk.errors import SlackApiError

from agent.sessions import current_deps
from agent.tools import tool_result

DESCRIPTION = """\
Post a final summary and archive the code channel.

Only call this when the user says the work is done or asks to wrap up. The \
summary is shared back to the message that started the session. After this, \
the session is over and you can't post again.\
"""


@tool(
    "archive_channel",
    DESCRIPTION,
    {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "A short wrap-up of what changed, where it lives, and anything left to do.",
            },
        },
        "required": ["summary"],
    },
)
async def archive_channel(args: dict) -> dict:
    deps = current_deps.get()
    try:
        posted = await deps.client.chat_postMessage(
            channel=deps.channel_id,
            markdown_text=args["summary"],
        )
        # Close the session while the channel can still be written to.
        await deps.client.agents_sessions_setStatus(
            channel_id=deps.channel_id,
            status="closed",
        )
        try:
            await deps.client.agents_conversations_archive(
                channel_id=deps.channel_id,
                summary_message_ts=posted["ts"],
            )
        except SlackApiError as e:
            # A channel started from Slack's own UI has no origin message to share back to.
            if e.response["error"] != "no_origin_link":
                raise
            await deps.client.agents_conversations_archive(channel_id=deps.channel_id)
    except SlackApiError as e:
        return tool_result(f"Could not archive the channel: {e.response['error']}")

    deps.session.archived = True
    return tool_result(
        "Posted the summary and archived the channel. The session is over."
    )
