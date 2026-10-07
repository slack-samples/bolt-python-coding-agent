from logging import Logger

from slack_bolt import Ack, Respond
from slack_sdk import WebClient

from agent import run_turn, session_store


def handle_agent_command(
    ack: Ack,
    command: dict,
    client: WebClient,
    respond: Respond,
    logger: Logger,
):
    """Handle a slash command the agent registered in a code channel.

    The command and its text become the next turn, like `/run-tests unit`, so the
    agent decides what each of its commands does.
    """
    ack()

    session = session_store.get(command["channel_id"])
    if session is None:
        respond("I don't have an active session here. Mention me to pick it back up.")
        return

    text = f"{command['command']} {command.get('text', '')}".strip()
    try:
        run_turn(
            client=client,
            session=session,
            text=text,
            user_id=command["user_id"],
        )
    except Exception as e:
        logger.exception("Failed to handle agent command")
        respond(f":warning: Something went wrong ({e}).")
