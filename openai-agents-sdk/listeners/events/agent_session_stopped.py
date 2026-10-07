from slack_bolt import BoltContext

from agent import session_store
from agent.approvals import pending_store


def handle_agent_session_stopped(context: BoltContext, event: dict):
    """Handle the native stop button.

    Stop all work for the session right away: drop any command waiting on
    approval and flag the session so the in-flight run posts nothing more. Don't
    post or call the agents.* methods after a stop; Slack updates the session
    status on its own.
    """
    channel_id = event.get("channel") or context.channel_id
    pending_store.discard(channel_id)

    session = session_store.get(channel_id)
    if session is not None:
        session.stopped = True
