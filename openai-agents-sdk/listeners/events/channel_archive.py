from slack_bolt import BoltContext

from agent import session_store
from agent.approvals import pending_store


def handle_channel_archive(context: BoltContext, event: dict):
    """Forget a code channel someone archived, and delete its working directory.

    When the agent archives the channel itself, `archive_channel` already ends
    the session and Bolt skips the app's own event.
    """
    channel_id = event.get("channel") or context.channel_id
    pending_store.discard(channel_id)
    session_store.discard(channel_id)
