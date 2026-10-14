from slack_bolt.context.async_context import AsyncBoltContext
from slack_sdk.web.async_client import AsyncWebClient

from agent import answer_request, find_session, run_turn


async def handle_app_mentioned(
    client: AsyncWebClient, context: AsyncBoltContext, event: dict
):
    """Handle an @mention by replying in place or creating a code channel.

    A mention in a normal channel is the entry point: the agent decides whether
    the request fits in a reply or calls `create_code_channel`. A mention inside
    a code channel is a turn in that session. That includes the request Slack
    seeds into a channel the agent just created, which starts its first turn.
    """
    channel_id = context.channel_id
    text = event.get("text", "").replace(f"<@{context.bot_user_id}>", "").strip()

    session = await find_session(client, channel_id)
    if session is not None:
        await run_turn(
            client=client, session=session, text=text, user_id=context.user_id
        )
        return

    await answer_request(
        client=client,
        channel_id=channel_id,
        message_ts=event["ts"],
        thread_ts=event.get("thread_ts"),
        text=text,
        user_id=context.user_id,
        in_dm=False,
    )
