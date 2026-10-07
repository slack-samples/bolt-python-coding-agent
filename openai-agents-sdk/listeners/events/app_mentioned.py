from logging import Logger

from slack_bolt import BoltContext
from slack_sdk import WebClient

from agent import (
    CodeChannelSession,
    RequestDeps,
    answer_request,
    run_turn,
    session_store,
)


def handle_app_mentioned(
    client: WebClient,
    context: BoltContext,
    event: dict,
    logger: Logger,
):
    """Handle an @mention by replying in place or creating a code channel.

    A mention in a normal channel is the entry point: the agent decides whether
    the request fits in a reply or calls `create_code_channel`. A mention inside
    a code channel is a turn in that session. That includes the request Slack
    seeds into a channel the agent just created, which starts its first turn.
    """
    channel_id = context.channel_id
    message_ts = event["ts"]
    thread_ts = event.get("thread_ts") or message_ts
    text = event.get("text", "").replace(f"<@{context.bot_user_id}>", "").strip()

    session = None
    try:
        session = session_store.get(channel_id) or _adopt_code_channel(
            client, channel_id
        )
        if session is not None:
            run_turn(
                client=client,
                session=session,
                text=text,
                user_id=context.user_id,
            )
            return

        if not text:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Mention me with a question or a coding task and a repo.",
            )
            return

        deps = RequestDeps(
            client=client,
            user_id=context.user_id,
            channel_id=channel_id,
            message_ts=message_ts,
            thread_ts=thread_ts,
        )
        reply = answer_request(text, deps)
        # When the agent created a code channel, the work continues there.
        if deps.code_channel_id is None:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                markdown_text=reply or "(the agent finished without a message)",
            )

    except Exception as e:
        logger.exception("Failed to handle app mention")
        # A code channel is one session, so replies there stay top-level.
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=None if session else thread_ts,
            text=f":warning: Something went wrong ({e}).",
        )


def _adopt_code_channel(
    client: WebClient,
    channel_id: str,
) -> CodeChannelSession | None:
    """Start a session for a code channel this app doesn't have state for yet.

    That's every new channel the agent creates, once its seeded request
    arrives, plus channels started from Slack's own UI or forgotten after a
    restart. `record_channel.record_type` is set on every code channel at
    creation, so it's the reliable way to recognize one.
    """
    channel = client.conversations_info(channel=channel_id)["channel"]
    properties = channel.get("properties", {})
    if properties.get("record_channel", {}).get("record_type") != "agent_channel":
        return None

    origin = properties.get("agent_session", {}).get("origin_link", {})
    session = CodeChannelSession(
        channel_id=channel_id,
        origin_channel_id=origin.get("channel_id"),
        origin_message_ts=origin.get("ts"),
    )
    session_store.put(session)
    return session
