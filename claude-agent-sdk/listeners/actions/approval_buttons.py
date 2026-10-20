"""Approve / Deny handler for a command awaiting approval in a code channel."""

from slack_bolt.async_app import AsyncAck
from slack_bolt.context.async_context import AsyncBoltContext
from slack_sdk.web.async_client import AsyncWebClient

from agent import resume_turn


async def handle_approval_buttons(
    ack: AsyncAck,
    action: dict,
    body: dict,
    context: AsyncBoltContext,
    client: AsyncWebClient,
):
    """Resume the paused run with the decision from whichever button was clicked."""
    await ack()
    await resume_turn(
        client=client,
        channel_id=context.channel_id,
        message_ts=body["message"]["ts"],
        approved=action["value"] == "approve",
    )
