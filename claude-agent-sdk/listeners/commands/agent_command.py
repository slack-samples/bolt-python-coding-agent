from slack_bolt.async_app import AsyncAck, AsyncRespond
from slack_sdk.web.async_client import AsyncWebClient

from agent import find_session, run_turn


async def handle_agent_command(
    ack: AsyncAck,
    command: dict,
    client: AsyncWebClient,
    respond: AsyncRespond,
):
    """Handle a slash command the agent registered in a code channel.

    The command and its text become the next turn, like `/run-tests unit`, so the
    agent decides what each of its commands does.
    """
    await ack()

    session = await find_session(client, command["channel_id"])
    if session is None:
        await respond("I don't have a session here. Mention me to start one.")
        return

    text = f"{command['command']} {command.get('text', '')}".strip()
    await run_turn(
        client=client, session=session, text=text, user_id=command["user_id"]
    )
