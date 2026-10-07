from logging import Logger

from slack_bolt import BoltContext
from slack_sdk import WebClient

from agent import run_turn, session_store


def handle_message(
    client: WebClient,
    context: BoltContext,
    event: dict,
    logger: Logger,
):
    """Handle a message inside a code channel as a turn — no @mention needed.

    In a code channel the user is talking to the agent directly, so we respond
    to plain messages. We only act when the channel is one of our active code
    channel sessions; messages elsewhere are ignored here (mentions start new
    channels via app_mentioned).
    """
    # Ignore edits, joins, or bot posts.
    if event.get("subtype") or event.get("bot_id"):
        return
    text = event.get("text", "").strip()
    # A message that mentions the agent also arrives as app_mention, which runs the turn.
    if not text or f"<@{context.bot_user_id}>" in text:
        return

    channel_id = context.channel_id
    session = session_store.get(channel_id)
    if session is None:
        return

    try:
        run_turn(
            client=client,
            session=session,
            text=text,
            user_id=context.user_id,
        )
    except Exception as e:
        logger.exception("Failed to handle code channel message")
        client.chat_postMessage(
            channel=channel_id, text=f":warning: Something went wrong ({e})."
        )
