"""The conversation around a request, read from Slack and given to the agent with it."""

import logging

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Enough earlier conversation to follow along without crowding the prompt.
MAX_MESSAGES = 50
MAX_MESSAGE_CHARS = 2000


def _transcript(messages: list[dict]) -> str:
    """One line per message, starting with who sent it."""
    lines = []
    for message in messages[-MAX_MESSAGES:]:
        sender = f"<@{message['user']}>" if message.get("user") else "An app"
        lines.append(f"{sender}: {message.get('text', '')[:MAX_MESSAGE_CHARS]}")
    return "\n".join(lines)


async def thread_context(
    client: AsyncWebClient, channel_id: str, thread_ts: str, *, before_ts: str
) -> str:
    """The messages in a thread that came before `before_ts`."""
    try:
        response = await client.conversations_replies(
            channel=channel_id, ts=thread_ts, limit=200
        )
    except SlackApiError as e:
        logger.warning("Couldn't read the thread: %s", e.response["error"])
        return ""
    messages = response.get("messages", [])
    return _transcript([m for m in messages if float(m["ts"]) < float(before_ts)])


async def recent_context(
    client: AsyncWebClient, channel_id: str, *, before_ts: str
) -> str:
    """The latest messages in a conversation before `before_ts`, like a direct message's."""
    try:
        response = await client.conversations_history(
            channel=channel_id, latest=before_ts, limit=20
        )
    except SlackApiError as e:
        logger.warning("Couldn't read the conversation: %s", e.response["error"])
        return ""
    # History comes newest first.
    return _transcript(list(reversed(response.get("messages", []))))


async def origin_context(client: AsyncWebClient, channel_id: str, ts: str) -> str:
    """The conversation before the message a code channel was started from."""
    # A direct message's context is the conversation before it, not a thread.
    if channel_id.startswith("D"):
        return await recent_context(client, channel_id, before_ts=ts)
    try:
        response = await client.conversations_replies(
            channel=channel_id, ts=ts, limit=1
        )
    except SlackApiError as e:
        logger.warning("Couldn't read the origin message: %s", e.response["error"])
        return ""
    messages = response.get("messages", [])
    thread_ts = messages[0].get("thread_ts") if messages else None
    if not thread_ts:
        return ""
    return await thread_context(client, channel_id, thread_ts, before_ts=ts)
