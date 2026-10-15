from slack_bolt.context.async_context import AsyncBoltContext

from agent import end_session


async def handle_channel_archive(context: AsyncBoltContext, event: dict):
    """Forget a code channel someone archived, and delete its working directory.

    When the agent archives the channel itself, its turn ends the session once
    `archive_channel` returns, and Bolt skips the app's own event.
    """
    end_session(event.get("channel") or context.channel_id)
