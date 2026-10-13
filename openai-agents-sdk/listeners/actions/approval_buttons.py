"""Approve / Deny handler for a command awaiting approval in a code channel."""

from slack_bolt import Ack, BoltContext
from slack_sdk import WebClient

from agent import resume_turn


def handle_approval_buttons(
    ack: Ack,
    action: dict,
    body: dict,
    context: BoltContext,
    client: WebClient,
):
    """Resume the paused run with the decision from whichever button was clicked."""
    ack()
    resume_turn(
        client=client,
        channel_id=context.channel_id,
        message_ts=body["message"]["ts"],
        approved=action["value"] == "approve",
    )
