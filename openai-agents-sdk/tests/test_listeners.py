import json
import logging
from unittest.mock import Mock, patch

from agents import ToolApprovalItem
from slack_bolt import BoltContext
from slack_sdk import WebClient

from agent import CodeChannelSession, RunOutcome, session_store
from agent.approvals import pending_store
from agent.tools import create_code_channel
from listeners.actions.approval_buttons import handle_approval_buttons
from listeners.events.agent_session_stopped import handle_agent_session_stopped
from listeners.events.app_home_opened import handle_app_home_opened
from listeners.events.app_mentioned import handle_app_mentioned
from listeners.events.channel_archive import handle_channel_archive
from listeners.events.message import handle_message
from tests.test_tools import invoke

test_logger = logging.getLogger(__name__)


class TestListeners:
    def setup_method(self):
        self.client = Mock(WebClient)
        self.context = Mock(BoltContext)
        self.context.bot_user_id = "UBOT"
        self.context.user_id = "U123"
        self.history = [{"role": "assistant", "content": "Done."}]

    def teardown_method(self):
        for channel_id in ("C_CODE", "C_ORIGIN", "C_ADOPTED"):
            session_store.discard(channel_id)
            pending_store.discard(channel_id)

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

    def test_message_with_a_mention_is_left_to_app_mention(self):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))
        self.context.channel_id = "C_CODE"

        with patch("agent.agent.start_run") as start_run:
            handle_message(
                client=self.client,
                context=self.context,
                event={"ts": "3.3", "text": "<@UBOT> again"},
                logger=test_logger,
            )

        start_run.assert_not_called()

    def pause_on(self, command: str, message_ts: str):
        """Run a turn in C_CODE that pauses on `command`, posting buttons at `message_ts`."""
        item = Mock(spec=ToolApprovalItem, arguments=json.dumps({"command": command}))
        self.client.chat_postMessage.return_value = {"ts": message_ts}
        with patch(
            "agent.agent.start_run",
            return_value=RunOutcome(
                pending_state=Mock(),
                pending_item=item,
                history=self.history,
            ),
        ):
            handle_message(
                client=self.client,
                context=self.context,
                event={"ts": "5.5", "text": f"run {command}"},
                logger=test_logger,
            )
        return item

    def click(self, value: str, message_ts: str):
        with patch(
            "agent.agent.resume_run",
            return_value=RunOutcome(final_output="Ran it.", history=self.history),
        ) as resume_run:
            handle_approval_buttons(
                ack=Mock(),
                action={"value": value},
                body={"message": {"ts": message_ts}},
                context=self.context,
                client=self.client,
                logger=test_logger,
            )
        return resume_run

    def test_approving_resumes_the_paused_run(self):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))
        self.context.channel_id = "C_CODE"
        self.pause_on("rm -rf build", "9.1")

        resume_run = self.click("approve", "9.1")

        state = resume_run.call_args.args[0]
        state.approve.assert_called_once()
        state.reject.assert_not_called()
        update = self.client.chat_update.call_args.kwargs
        assert update["ts"] == "9.1"
        assert "Approved" in update["text"]
        assert "rm -rf build" in update["text"]

    def test_denying_resumes_the_paused_run_with_a_rejection(self):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))
        self.context.channel_id = "C_CODE"
        self.pause_on("rm -rf build", "9.1")

        resume_run = self.click("deny", "9.1")

        state = resume_run.call_args.args[0]
        state.reject.assert_called_once()
        state.approve.assert_not_called()
        assert "Denied" in self.client.chat_update.call_args.kwargs["text"]

    def test_stale_approval_never_approves_a_newer_command(self):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))
        self.context.channel_id = "C_CODE"
        self.pause_on("rm -rf build", "9.1")
        self.pause_on("git push --force", "9.2")

        resume_run = self.click("approve", "9.1")

        resume_run.assert_not_called()
        update = self.client.chat_update.call_args.kwargs
        assert update["ts"] == "9.1"
        assert "expired" in update["text"]
        assert pending_store.pop("C_CODE", "9.2").command == "git push --force"

    def test_archiving_from_slack_forgets_the_session(self, tmp_path):
        workdir = tmp_path / "clone"
        workdir.mkdir()
        session_store.put(CodeChannelSession(channel_id="C_CODE", workdir=str(workdir)))
        self.context.channel_id = "C_CODE"
        self.pause_on("rm -rf build", "9.1")

        handle_channel_archive(context=self.context, event={"channel": "C_CODE"})

        assert session_store.get("C_CODE") is None
        assert pending_store.pop("C_CODE", "9.1") is None
        assert not workdir.exists()

    def test_home_tab_is_published_only_for_home(self):
        handle_app_home_opened(
            client=self.client, context=self.context, event={"tab": "messages"}
        )
        self.client.views_publish.assert_not_called()

        handle_app_home_opened(
            client=self.client, context=self.context, event={"tab": "home"}
        )
        publish = self.client.views_publish.call_args.kwargs
        assert publish["user_id"] == "U123"
        assert publish["view"].to_dict()["type"] == "home"

    def test_stopped_session_posts_nothing(self):
        session = CodeChannelSession(channel_id="C_CODE")
        session_store.put(session)
        self.context.channel_id = "C_CODE"

        def stop_mid_run(_input, _deps):
            handle_agent_session_stopped(
                context=self.context, event={"channel": "C_CODE"}
            )
            return RunOutcome(final_output="Done.", history=self.history)

        with patch("agent.agent.start_run", side_effect=stop_mid_run):
            handle_message(
                client=self.client,
                context=self.context,
                event={"ts": "4.4", "text": "keep going"},
                logger=test_logger,
            )

        assert session.stopped is True
        self.client.chat_postMessage.assert_not_called()
        statuses = [
            c.kwargs["status"]
            for c in self.client.agents_sessions_setStatus.call_args_list
        ]
        assert statuses == ["processing"]
