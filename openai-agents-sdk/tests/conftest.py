from unittest.mock import Mock

import pytest
from agents import set_tracing_disabled
from slack_bolt.context.async_context import AsyncBoltContext
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from agent import turns
from agent.approvals import pending_store
from agent.sessions import session_store

# Tests never reach OpenAI, so there are no traces to send.
set_tracing_disabled(True)


@pytest.fixture(autouse=True)
def forget_sessions():
    """Start every test with no sessions, approvals, or known channels."""
    yield
    for channel_id in list(session_store._store):
        session_store.discard(channel_id)
    pending_store._store.clear()
    turns._other_channels.clear()


@pytest.fixture
def client() -> Mock:
    """A Slack client whose methods match the real one's, so a wrong call fails."""
    client = Mock(AsyncWebClient)
    client.chat_postMessage.return_value = {"ts": "8.8"}
    return client


@pytest.fixture
def context() -> Mock:
    context = Mock(AsyncBoltContext)
    context.bot_user_id = "UBOT"
    context.user_id = "U123"
    context.channel_id = "C_CODE"
    return context


def slack_error(error: str) -> SlackApiError:
    return SlackApiError(message=error, response={"ok": False, "error": error})


def code_channel_info(origin_channel_id: str = "C_ORIGIN", origin_ts: str = "1.1"):
    """A `conversations.info` response for a code channel started from a message."""
    return {
        "channel": {
            "properties": {
                "record_channel": {"record_type": "agent_channel"},
                "agent_session": {
                    "origin_link": {"channel_id": origin_channel_id, "ts": origin_ts}
                },
            }
        }
    }
