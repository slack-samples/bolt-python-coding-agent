from slack_bolt import BoltContext

from agent import end_session


def handle_channel_archive(context: BoltContext, event: dict):
    """Forget a code channel someone archived, and delete its working directory.

    When the agent archives the channel itself, `archive_channel` already ends
    the session and Bolt skips the app's own event.
    """
    end_session(event.get("channel") or context.channel_id)
