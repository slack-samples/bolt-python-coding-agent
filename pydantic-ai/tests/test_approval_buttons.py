from unittest.mock import AsyncMock, Mock, patch

from agent.approvals import pending_store
from agent.outcome import RunOutcome
from agent.sessions import CodeChannelSession, session_store
from listeners.actions.approval_buttons import handle_approval_buttons
from listeners.events.message import handle_message

HISTORY = [{"role": "assistant", "content": "Done."}]


class TestApprovalButtons:
    async def send(self, client, context, text: str, outcome: RunOutcome, ts="8.8"):
        """Send a message in C_CODE whose turn ends with `outcome`."""
        client.chat_postMessage.return_value = {"ts": ts}
        with patch("agent.turns.start_run", return_value=outcome):
            await handle_message(
                client=client, context=context, event={"ts": "5.5", "text": text}
            )

    async def pause_on(self, client, context, command: str, message_ts: str) -> Mock:
        """Run a turn in C_CODE that pauses on `command`, posting buttons at `message_ts`."""
        session_store.put(session_store.get("C_CODE") or CodeChannelSession("C_CODE"))
        paused = Mock()
        outcome = RunOutcome(paused=paused, command=command, history=HISTORY)
        await self.send(client, context, f"run {command}", outcome, message_ts)
        return paused

    async def click(self, client, context, value: str, message_ts: str, resumed=None):
        with patch(
            "agent.turns.resume_run",
            return_value=resumed or RunOutcome(final_output="Ran it.", history=HISTORY),
        ) as resume_run:
            await handle_approval_buttons(
                ack=AsyncMock(),
                action={"value": value},
                body={"message": {"ts": message_ts}},
                context=context,
                client=client,
            )
        return resume_run

    async def test_approving_resumes_the_paused_run(self, client, context):
        paused = await self.pause_on(client, context, "rm -rf build", "9.1")

        resume_run = await self.click(client, context, "approve", "9.1")

        assert resume_run.call_args.args[:2] == (paused, True)
        update = client.chat_update.call_args.kwargs
        assert update["ts"] == "9.1"
        assert "Approved" in update["text"]
        assert "rm -rf build" in update["text"]

    async def test_denying_resumes_the_paused_run_with_a_rejection(
        self, client, context
    ):
        paused = await self.pause_on(client, context, "rm -rf build", "9.1")

        resume_run = await self.click(client, context, "deny", "9.1")

        assert resume_run.call_args.args[:2] == (paused, False)
        assert "Denied" in client.chat_update.call_args.kwargs["text"]

    async def test_stale_approval_never_approves_a_newer_command(self, client, context):
        await self.pause_on(client, context, "rm -rf build", "9.1")
        await self.pause_on(client, context, "git push --force", "9.2")

        resume_run = await self.click(client, context, "approve", "9.1")

        resume_run.assert_not_called()
        update = client.chat_update.call_args.kwargs
        assert update["ts"] == "9.1"
        assert "expired" in update["text"]
        assert pending_store.pop("C_CODE", "9.2").command == "git push --force"

    async def test_a_newer_message_retires_the_pending_approval(self, client, context):
        await self.pause_on(client, context, "rm -rf build", "9.1")
        newer = [{"role": "assistant", "content": "Newer."}]

        await self.send(
            client,
            context,
            "never mind",
            RunOutcome(final_output="Newer.", history=newer),
        )

        # The buttons say the command was skipped, and a late click resumes nothing.
        skipped = client.chat_update.call_args.kwargs
        assert skipped["ts"] == "9.1"
        assert "Skipped" in skipped["text"]
        resume_run = await self.click(client, context, "approve", "9.1")
        resume_run.assert_not_called()
        assert session_store.get("C_CODE").history == newer

    async def test_messages_sent_during_a_resumed_command_run_next(
        self, client, context
    ):
        await self.pause_on(client, context, "pytest", "9.1")
        texts = []

        async def resumed(_paused, _approved, _deps):
            await handle_message(
                client=client, context=context, event={"ts": "5.6", "text": "then lint"}
            )
            return RunOutcome(final_output="Tests pass.", history=HISTORY)

        async def start(_history, text, _deps):
            texts.append(text)
            return RunOutcome(final_output="Linted.", history=HISTORY)

        with (
            patch("agent.turns.resume_run", side_effect=resumed),
            patch("agent.turns.start_run", side_effect=start),
        ):
            await handle_approval_buttons(
                ack=AsyncMock(),
                action={"value": "approve"},
                body={"message": {"ts": "9.1"}},
                context=context,
                client=client,
            )

        assert texts == ["<@U123>: then lint"]

    async def test_a_failed_resume_leaves_processing(self, client, context):
        await self.pause_on(client, context, "rm -rf build", "9.1")

        with patch("agent.turns.resume_run", side_effect=RuntimeError("boom")):
            await handle_approval_buttons(
                ack=AsyncMock(),
                action={"value": "approve"},
                body={"message": {"ts": "9.1"}},
                context=context,
                client=client,
            )

        assert "boom" in client.chat_postMessage.call_args.kwargs["text"]
        client.agents_sessions_setStatus.assert_called_with(
            channel_id="C_CODE", status="active"
        )
