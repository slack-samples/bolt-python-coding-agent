from slack_bolt import BoltContext
from slack_sdk import WebClient

from agent import stop_turn


def handle_agent_session_stopped(client: WebClient, context: BoltContext, event: dict):
    """Handle the native stop button by stopping the channel's turn."""
    stop_turn(client=client, channel_id=event.get("channel") or context.channel_id)
