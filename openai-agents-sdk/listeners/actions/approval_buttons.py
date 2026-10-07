"""Approve / Deny handler for a command awaiting approval in a code channel."""

from logging import Logger

from slack_bolt import Ack, BoltContext
from slack_sdk import WebClient
from slack_sdk.models.blocks import MarkdownTextObject, SectionBlock

from agent import resume_turn
from agent.approvals import pending_store


def handle_approval_buttons(
    ack: Ack,
    action: dict,
    body: dict,
    context: BoltContext,
    client: WebClient,
    logger: Logger,
):
    """Resume the paused run with the decision from whichever button was clicked."""
    ack()
    approved = action["value"] == "approve"
    channel_id = context.channel_id
    message_ts = body["message"]["ts"]
    # Only the run these buttons were posted for, never a newer one in the channel.
    pending = pending_store.pop(channel_id, message_ts)

    # Replace the buttons so the decision is visible and can't be re-clicked.
    if pending is None:
        text = ":hourglass: This approval has expired — please ask me again."
    elif approved:
        text = f":white_check_mark: *Approved:* ```{pending.command}```"
    else:
        text = f":x: *Denied:* ```{pending.command}```"
    try:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=text,
            blocks=[
                SectionBlock(text=MarkdownTextObject(text=text)),
            ],
        )
    except Exception:
        logger.exception("Failed to update approval message")

    if pending is None:
        return

    if approved:
        pending.state.approve(pending.approval_item)
    else:
        pending.state.reject(
            pending.approval_item,
            rejection_message="The user denied running this command.",
        )
    resume_turn(pending=pending)
