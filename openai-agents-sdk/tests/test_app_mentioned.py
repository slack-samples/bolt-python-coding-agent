import logging
from unittest.mock import Mock, patch

from slack_bolt import BoltContext
from slack_sdk import WebClient

from agent import CodeChannelSession, RunOutcome, session_store
from agent.tools import create_code_channel
from listeners.events.app_mentioned import handle_app_mentioned
from tests.test_tools import invoke

test_logger = logging.getLogger(__name__)


class TestAppMentioned:
    def setup_method(self):
        self.client = Mock(WebClient)
        self.context = Mock(BoltContext)
        self.context.bot_user_id = "UBOT"
        self.context.user_id = "U123"
        self.history = [{"role": "assistant", "content": "Done."}]

    def teardown_method(self):
        for channel_id in ("C_CODE", "C_ORIGIN", "C_ADOPTED"):
            session_store.discard(channel_id)

    def mention_in_origin(self, answer, text="<@UBOT> fix the login test"):
        self.context.channel_id = "C_ORIGIN"
        self.client.conversations_info.return_value = {"channel": {"properties": {}}}
        self.client.agents_conversations_create.return_value = {"channel_id": "C_CODE"}

        with (
            patch("listeners.events.app_mentioned.answer_request", side_effect=answer),
            patch(
                "agent.agent.start_run",
                return_value=RunOutcome(final_output="Done.", history=self.history),
            ) as start_run,
        ):
            handle_app_mentioned(
                client=self.client,
                context=self.context,
                event={"ts": "1.1", "text": text},
                logger=test_logger,
            )
        return start_run

    def test_mention_answered_in_place_opens_no_channel(self):
        start_run = self.mention_in_origin(
            lambda _text, _deps: "It's a billing service.",
            text="<@UBOT> what does this repo do?",
        )

        self.client.agents_conversations_create.assert_not_called()
        start_run.assert_not_called()
        reply = self.client.chat_postMessage.call_args.kwargs
        assert reply == {
            "channel": "C_ORIGIN",
            "thread_ts": "1.1",
            "markdown_text": "It's a billing service.",
        }

    def test_creating_a_channel_leaves_the_first_turn_to_the_seeded_mention(self):
        start_run = self.mention_in_origin(
            lambda _text, deps: invoke(
                create_code_channel, deps, title="Fix login test"
            )
        )

        create = self.client.agents_conversations_create.call_args.kwargs
        assert create["origin_channel_id"] == "C_ORIGIN"
        assert create["origin_message_ts"] == "1.1"
        assert create["session_id"] == "C_ORIGIN-1.1"
        # Slack seeds the new channel with the request, and that mention runs the turn.
        start_run.assert_not_called()
        posts = [c.kwargs for c in self.client.chat_postMessage.call_args_list]
        assert posts == [
            {
                "channel": "C_ORIGIN",
                "thread_ts": "1.1",
                "text": "On it! Follow along in <#C_CODE>.",
            }
        ]

    def test_creating_a_channel_twice_points_to_it_once(self):
        def create_twice(_text, deps):
            invoke(create_code_channel, deps, title="Fix login test")
            return invoke(create_code_channel, deps, title="Fix the login test")

        self.mention_in_origin(create_twice)

        sessions = [
            c.kwargs["session_id"]
            for c in self.client.agents_conversations_create.call_args_list
        ]
        assert sessions == ["C_ORIGIN-1.1", "C_ORIGIN-1.1"]
        assert self.client.chat_postMessage.call_count == 1

    def test_failed_turn_in_a_code_channel_warns_top_level(self):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))
        self.context.channel_id = "C_CODE"

        with patch("agent.agent.start_run", side_effect=RuntimeError("boom")):
            handle_app_mentioned(
                client=self.client,
                context=self.context,
                event={"ts": "6.6", "text": "<@UBOT> keep going"},
                logger=test_logger,
            )

        warning = self.client.chat_postMessage.call_args.kwargs
        assert warning["channel"] == "C_CODE"
        assert warning["thread_ts"] is None
        assert "boom" in warning["text"]

    def test_mention_in_an_unknown_code_channel_adopts_it(self):
        self.context.channel_id = "C_ADOPTED"
        self.client.conversations_info.return_value = {
            "channel": {
                "properties": {
                    "record_channel": {"record_type": "agent_channel"},
                    "agent_session": {
                        "origin_link": {"channel_id": "C_ORIGIN", "ts": "1.1"}
                    },
                }
            }
        }

        with patch(
            "agent.agent.start_run",
            return_value=RunOutcome(final_output="Hi.", history=self.history),
        ):
            handle_app_mentioned(
                client=self.client,
                context=self.context,
                event={"ts": "2.2", "text": "<@UBOT> take a look"},
                logger=test_logger,
            )

        self.client.agents_conversations_create.assert_not_called()
        assert session_store.get("C_ADOPTED").origin_channel_id == "C_ORIGIN"
