from slack_bolt.context.async_context import AsyncBoltContext
from slack_sdk.web.async_client import AsyncWebClient

from agent import answer_request, find_session, run_turn


async def handle_message(
    client: AsyncWebClient, context: AsyncBoltContext, event: dict
):
    """Handle a direct message, or a message in a code channel, without an @mention.

    A direct message is answered like a mention: in place, or with a code channel
    for bigger work. In a code channel the people in it are talking to the agent
    directly, so every message is a turn. Messages anywhere else are left alone.
    """
    # Ignore edits, joins, or bot posts.
    if event.get("subtype") or event.get("bot_id"):
        return
    mention = f"<@{context.bot_user_id}>"
    text = event.get("text", "").strip()
    channel_id = context.channel_id

    if event.get("channel_type") == "im":
        await answer_request(
            client=client,
            channel_id=channel_id,
            message_ts=event["ts"],
            thread_ts=event.get("thread_ts"),
            text=text.replace(mention, "").strip(),
            user_id=context.user_id,
            in_dm=True,
        )
        return

    # A message that mentions the agent also arrives as app_mention, which runs the turn.
    if not text or mention in text:
        return
    session = await find_session(client, channel_id)
    if session is None:
        return
    await run_turn(client=client, session=session, text=text, user_id=context.user_id)
