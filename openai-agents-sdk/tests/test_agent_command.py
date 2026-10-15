from unittest.mock import AsyncMock, patch

from agent.outcome import RunOutcome
from agent.sessions import CodeChannelSession, session_store
from listeners.commands.agent_command import handle_agent_command


class TestAgentCommand:
    async def run_command(self, client, **command):
        ack, respond = AsyncMock(), AsyncMock()
        await handle_agent_command(
            ack=ack,
            command={"user_id": "U123", "command": "/run-tests", **command},
            client=client,
            respond=respond,
        )
        return ack, respond

    async def test_command_in_a_code_channel_runs_a_turn(self, client):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))

        with patch(
            "agent.turns.start_run",
            return_value=RunOutcome(final_output="Tests passed.", history=[]),
        ) as start_run:
            ack, respond = await self.run_command(
                client, channel_id="C_CODE", text="unit"
            )

        ack.assert_awaited_once()
        assert start_run.call_args.args[1] == "<@U123>: /run-tests unit"
        respond.assert_not_called()

    async def test_command_without_a_session_explains_itself(self, client):
        client.conversations_info.return_value = {"channel": {"properties": {}}}

        with patch("agent.turns.start_run") as start_run:
            ack, respond = await self.run_command(client, channel_id="C_OTHER")

        ack.assert_awaited_once()
        start_run.assert_not_called()
        assert "Mention me" in respond.call_args.args[0]
