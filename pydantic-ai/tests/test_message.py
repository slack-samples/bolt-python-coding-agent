from unittest.mock import patch

from agent.outcome import RunOutcome
from agent.sessions import CodeChannelSession, session_store
from listeners.events.message import handle_message
from tests.conftest import code_channel_info


class TestMessage:
    async def send(self, client, context, text: str, **event):
        await handle_message(
            client=client, context=context, event={"ts": "3.3", "text": text, **event}
        )

    async def test_message_in_a_code_channel_runs_a_turn(self, client, context):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))

        with patch(
            "agent.turns.start_run",
            return_value=RunOutcome(final_output="Done.", history=[]),
        ) as start_run:
            await self.send(client, context, "keep going")

        assert start_run.call_args.args[1] == "<@U123>: keep going"
        client.chat_postMessage.assert_called_once_with(
            channel="C_CODE", markdown_text="Done."
        )
        statuses = [
            c.kwargs["status"] for c in client.agents_sessions_setStatus.call_args_list
        ]
        assert statuses == ["processing", "active"]

    async def test_message_with_a_mention_is_left_to_app_mention(self, client, context):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))

        with patch("agent.turns.start_run") as start_run:
            await self.send(client, context, "<@UBOT> again")

        start_run.assert_not_called()

    async def test_messages_during_a_turn_run_together_next(self, client, context):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))
        texts = []

        async def run(_history, text, _deps):
            texts.append(text)
            if len(texts) == 1:
                # Two people follow up while the first turn is still running.
                await self.send(client, context, "also this")
                context.user_id = "U456"
                await self.send(client, context, "and this")
            return RunOutcome(final_output="Done.", history=[])

        with patch("agent.turns.start_run", side_effect=run):
            await self.send(client, context, "start")

        assert texts == ["<@U123>: start", "<@U123>: also this\n\n<@U456>: and this"]

    async def test_direct_message_is_answered_in_place(self, client, context):
        context.channel_id = "D123"
        client.conversations_history.return_value = {
            "messages": [{"ts": "2.2", "user": "U123", "text": "I use billing-service"}]
        }

        with patch("agent.turns.run_request", return_value="Sure.") as run_request:
            await self.send(client, context, "what's it written in?", channel_type="im")

        prompt = run_request.call_args.args[0]
        assert "<@U123>: I use billing-service" in prompt
        assert prompt.endswith("<@U123>: what's it written in?")
        client.chat_postMessage.assert_called_once_with(
            channel="D123", thread_ts=None, markdown_text="Sure."
        )

    async def test_message_in_another_channel_is_looked_up_once(self, client, context):
        context.channel_id = "C_GENERAL"
        client.conversations_info.return_value = {"channel": {"properties": {}}}

        with patch("agent.turns.start_run") as start_run:
            await self.send(client, context, "lunch?")
            await self.send(client, context, "anyone?")

        client.conversations_info.assert_called_once()
        start_run.assert_not_called()

    async def test_message_in_a_forgotten_code_channel_picks_it_up(
        self, client, context
    ):
        client.conversations_info.return_value = code_channel_info()
        client.conversations_replies.return_value = {
            "messages": [{"ts": "1.1", "user": "U123", "text": "fix it"}]
        }

        with patch(
            "agent.turns.start_run",
            return_value=RunOutcome(final_output="Back.", history=[]),
        ) as start_run:
            await self.send(client, context, "you there?")

        start_run.assert_called_once()
        assert session_store.get("C_CODE").origin_channel_id == "C_ORIGIN"
