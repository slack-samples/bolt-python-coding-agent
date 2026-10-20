from slack_bolt.context.async_context import AsyncBoltContext
from slack_sdk.web.async_client import AsyncWebClient

from agent import stop_turn


async def handle_agent_session_stopped(
    client: AsyncWebClient, context: AsyncBoltContext, event: dict
):
    """Handle the native stop button by stopping the channel's turn."""
    await stop_turn(
        client=client, channel_id=event.get("channel") or context.channel_id
    )
