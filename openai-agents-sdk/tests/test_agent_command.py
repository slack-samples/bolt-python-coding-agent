import logging
from unittest.mock import Mock, patch

from slack_sdk import WebClient

from agent import CodeChannelSession, RunOutcome, session_store
from listeners.commands.agent_command import handle_agent_command

test_logger = logging.getLogger(__name__)


class TestAgentCommand:
    def setup_method(self):
        self.client = Mock(WebClient)
        self.ack = Mock()
        self.respond = Mock()

    def teardown_method(self):
        session_store.discard("C_CODE")

    def test_command_in_a_code_channel_runs_a_turn(self):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))

        with patch(
            "agent.agent.start_run",
            return_value=RunOutcome(final_output="Tests passed.", history=[]),
        ) as start_run:
            handle_agent_command(
                ack=self.ack,
                command={
                    "channel_id": "C_CODE",
                    "user_id": "U123",
                    "command": "/run-tests",
                    "text": "unit",
                },
                client=self.client,
                respond=self.respond,
                logger=test_logger,
            )

        self.ack.assert_called_once()
        assert start_run.call_args.args[0][-1]["content"] == "/run-tests unit"
        self.respond.assert_not_called()

    def test_command_without_a_session_explains_itself(self):
        with patch("agent.agent.start_run") as start_run:
            handle_agent_command(
                ack=self.ack,
                command={
                    "channel_id": "C_OTHER",
                    "user_id": "U123",
                    "command": "/run-tests",
                },
                client=self.client,
                respond=self.respond,
                logger=test_logger,
            )

        self.ack.assert_called_once()
        start_run.assert_not_called()
        assert "Mention me" in self.respond.call_args.args[0]
