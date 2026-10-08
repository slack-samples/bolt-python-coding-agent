from logging import Logger

from slack_bolt import BoltContext
from slack_sdk import WebClient
from slack_sdk.models.blocks import MarkdownTextObject, SectionBlock

from agent import session_store
from agent.approvals import pending_store


def handle_agent_session_stopped(
    client: WebClient,
    context: BoltContext,
    event: dict,
    logger: Logger,
):
    """Handle the native stop button.

    Slack doesn't change the session status on a stop, so the app stops its
    work, cleans up, confirms the stop, and moves the session out of
    `processing` itself.
    """
    channel_id = event.get("channel") or context.channel_id

    # Stop in-progress work: the running turn sees this flag, runs no more
    # commands, and posts nothing when it finishes.
    session = session_store.get(channel_id)
    if session is not None:
        session.stopped = True

    # Clean up a command waiting on approval so its buttons can't resume it.
    pending = pending_store.discard(channel_id)
    if pending is not None:
        text = f":octagonal_sign: *Stopped before running:* ```{pending.command}```"
        try:
            client.chat_update(
                channel=channel_id,
                ts=pending.message_ts,
                text=text,
                blocks=[
                    SectionBlock(text=MarkdownTextObject(text=text)),
                ],
            )
        except Exception:
            logger.exception("Failed to update the approval message")

    client.chat_postMessage(
        channel=channel_id,
        text="Stopped. Send a message to pick back up.",
    )
    client.agents_sessions_setStatus(
        channel_id=channel_id,
        status="active",
    )
