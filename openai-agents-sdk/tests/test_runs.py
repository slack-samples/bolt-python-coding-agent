"""Real agent runs with a scripted model, covering the seams where the turn code meets the SDK."""

from pathlib import Path
from unittest.mock import patch

import agent.agent as agents_module
from agent.agent import resume_run, run_request, start_run
from agent.deps import AgentDeps, RequestDeps
from agent.store import CodeChannelSession
from tests.fake_model import FakeModel, call, say


def coding_agent(script) -> tuple:
    model = FakeModel(script)
    return patch.object(
        agents_module, "agent", agents_module.agent.clone(model=model)
    ), model


class TestRuns:
    async def test_a_command_needing_approval_pauses_and_runs_once_approved(
        self, client, tmp_path
    ):
        session = CodeChannelSession(channel_id="C_CODE", workdir=str(tmp_path))
        deps = AgentDeps(client=client, session=session, user_id="U123")
        replaced, _ = coding_agent(
            lambda n: (
                call("run_command", command="touch made", directory=None)
                if n == 1
                else say("Made it.")
            )
        )

        with replaced:
            outcome = await start_run([], "<@U123>: make a file", deps)
            assert outcome.needs_approval
            assert outcome.command == "touch made"
            assert not (tmp_path / "made").exists()

            resumed = await resume_run(outcome.paused, True, deps)

        assert resumed.final_output == "Made it."
        assert (tmp_path / "made").exists()

    async def test_a_denied_command_never_runs(self, client, tmp_path):
        session = CodeChannelSession(channel_id="C_CODE", workdir=str(tmp_path))
        deps = AgentDeps(client=client, session=session, user_id="U123")
        replaced, model = coding_agent(
            lambda n: (
                call("run_command", command="touch made", directory=None)
                if n == 1
                else say("Okay.")
            )
        )

        with replaced:
            outcome = await start_run([], "<@U123>: make a file", deps)
            resumed = await resume_run(outcome.paused, False, deps)

        assert resumed.final_output == "Okay."
        assert not (tmp_path / "made").exists()
        outputs = [
            i for i in model.inputs[-1] if i.get("type") == "function_call_output"
        ]
        assert "denied" in str(outputs[-1]["output"])

    async def test_a_stopped_session_skips_tool_calls(self, client):
        session = CodeChannelSession(channel_id="C_CODE", stopped=True)
        deps = AgentDeps(client=client, session=session, user_id="U123")
        item = {"key": "repo", "label": "repo", "icon": None, "url": None}
        replaced, _ = coding_agent(
            lambda n: (
                call("set_context_bar", items=[item]) if n == 1 else say("Stopped.")
            )
        )

        with replaced:
            outcome = await start_run([], "<@U123>: go", deps)

        assert outcome.final_output == "Stopped."
        client.agents_conversations_setProperties.assert_not_called()

    async def test_running_out_of_turns_ends_with_a_message(self, client, tmp_path):
        session = CodeChannelSession(channel_id="C_CODE", workdir=str(tmp_path))
        deps = AgentDeps(client=client, session=session, user_id="U123")
        replaced, model = coding_agent(
            lambda n: call("run_command", command="pwd", directory=None)
        )

        with replaced, patch.object(agents_module, "MAX_TURNS", 3):
            outcome = await start_run([], "<@U123>: go", deps)

        assert len(model.inputs) == 3
        assert "steps" in outcome.final_output
        # The turn's work stays in history for the next turn.
        assert outcome.history[-1]["role"] == "assistant"

    async def test_archiving_ends_the_turn(self, client):
        client.chat_postMessage.return_value = {"ts": "9.9"}
        session = CodeChannelSession(channel_id="C_CODE")
        deps = AgentDeps(client=client, session=session, user_id="U123")
        replaced, model = coding_agent(
            lambda n: (
                call("archive_channel", summary="Done.") if n == 1 else say("Extra.")
            )
        )

        with replaced:
            await start_run([], "<@U123>: we're done", deps)

        assert session.archived
        assert len(model.inputs) == 1

    async def test_creating_a_channel_ends_the_request(self, client):
        client.agents_conversations_create.return_value = {"channel_id": "C_NEW"}
        deps = RequestDeps(
            client=client,
            user_id="U123",
            channel_id="C_ORIGIN",
            message_ts="1.1",
            thread_ts="1.1",
        )
        model = FakeModel(
            lambda n: (
                call("create_code_channel", title="Fix it") if n == 1 else say("Extra.")
            )
        )

        with patch.object(
            agents_module,
            "request_agent",
            agents_module.request_agent.clone(model=model),
        ):
            await run_request("<@U123>: fix the login test", deps)

        assert deps.code_channel_id == "C_NEW"
        assert len(model.inputs) == 1

    async def test_file_tools_work_without_approval(self, client, tmp_path):
        session = CodeChannelSession(channel_id="C_CODE", workdir=str(tmp_path))
        deps = AgentDeps(client=client, session=session, user_id="U123")
        steps = [
            call("write_file", path="src/hello.py", content="print('hi')\n"),
            call("edit_file", path="src/hello.py", old_text="hi", new_text="hello"),
            say("Wrote it."),
        ]
        replaced, _ = coding_agent(lambda n: steps[n - 1])

        with replaced:
            outcome = await start_run([], "<@U123>: write hello", deps)

        assert outcome.final_output == "Wrote it."
        assert Path(tmp_path / "src" / "hello.py").read_text() == "print('hello')\n"
