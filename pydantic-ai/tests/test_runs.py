"""Real agent runs with a scripted model, covering the seams where the turn code meets Pydantic AI."""

from pathlib import Path
from unittest.mock import patch

from pydantic_ai.messages import ModelResponse, ToolReturnPart

import agent.agent as agents_module
from agent.agent import resume_run, run_request, start_run
from agent.sessions import AgentDeps, CodeChannelSession, RequestDeps
from tests.fake_model import FakeModel, call, say


def coding_agent(script) -> tuple:
    model = FakeModel(script)
    return agents_module.agent.override(model=model), model


def tool_returns(messages) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]


class TestRuns:
    async def test_a_command_needing_approval_pauses_and_runs_once_approved(
        self, client, tmp_path
    ):
        session = CodeChannelSession(channel_id="C_CODE", workdir=str(tmp_path))
        deps = AgentDeps(client=client, session=session)
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
        deps = AgentDeps(client=client, session=session)
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
        assert "denied" in tool_returns(model.inputs[-1])[-1].content

    async def test_a_dropped_approval_leaves_a_history_the_next_turn_takes(
        self, client, tmp_path
    ):
        session = CodeChannelSession(channel_id="C_CODE", workdir=str(tmp_path))
        deps = AgentDeps(client=client, session=session)
        replaced, model = coding_agent(
            lambda n: (
                call("run_command", command="touch made", directory=None)
                if n == 1
                else say("Hi.")
            )
        )

        with replaced:
            outcome = await start_run([], "<@U123>: make a file", deps)
            # A newer message replaces the paused run instead of resuming it.
            next_turn = await start_run(outcome.history, "<@U123>: never mind", deps)

        assert next_turn.final_output == "Hi."
        assert not (tmp_path / "made").exists()
        assert "Not run" in tool_returns(model.inputs[-1])[-1].content

    async def test_a_stopped_session_skips_tool_calls(self, client):
        session = CodeChannelSession(channel_id="C_CODE", stopped=True)
        deps = AgentDeps(client=client, session=session)
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

    async def test_a_stopped_session_skips_archiving(self, client):
        session = CodeChannelSession(channel_id="C_CODE", stopped=True)
        deps = AgentDeps(client=client, session=session)
        replaced, _ = coding_agent(
            lambda n: (
                call("archive_channel", summary="Done.") if n == 1 else say("Stopped.")
            )
        )

        with replaced:
            outcome = await start_run([], "<@U123>: go", deps)

        assert outcome.final_output == "Stopped."
        assert not session.archived
        client.agents_conversations_archive.assert_not_called()

    async def test_a_tool_that_raises_tells_the_model(self, client):
        client.agents_sessions_rename.side_effect = RuntimeError("boom")
        session = CodeChannelSession(channel_id="C_CODE")
        deps = AgentDeps(client=client, session=session)
        replaced, model = coding_agent(
            lambda n: (
                call("rename_session", title="Fix it") if n == 1 else say("Sorry.")
            )
        )

        with replaced:
            outcome = await start_run([], "<@U123>: rename", deps)

        assert outcome.final_output == "Sorry."
        assert "error occurred" in tool_returns(model.inputs[-1])[-1].content

    async def test_running_out_of_turns_ends_with_a_message(self, client, tmp_path):
        session = CodeChannelSession(channel_id="C_CODE", workdir=str(tmp_path))
        deps = AgentDeps(client=client, session=session)
        replaced, model = coding_agent(
            lambda n: call("run_command", command="pwd", directory=None)
        )

        with replaced, patch.object(agents_module, "MAX_TURNS", 3):
            outcome = await start_run([], "<@U123>: go", deps)

        assert len(model.inputs) == 3
        assert "steps" in outcome.final_output
        # The turn's work stays in history for the next turn.
        assert isinstance(outcome.history[-1], ModelResponse)
        assert len(tool_returns(outcome.history)) == 3

    async def test_archiving_ends_the_turn(self, client):
        client.chat_postMessage.return_value = {"ts": "9.9"}
        session = CodeChannelSession(channel_id="C_CODE")
        deps = AgentDeps(client=client, session=session)
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
            channel_id="C_ORIGIN",
            message_ts="1.1",
            thread_ts="1.1",
        )
        model = FakeModel(
            lambda n: (
                call("create_code_channel", title="Fix it") if n == 1 else say("Extra.")
            )
        )

        with agents_module.request_agent.override(model=model):
            reply = await run_request("<@U123>: fix the login test", deps)

        assert deps.code_channel_id == "C_NEW"
        assert reply is None
        assert len(model.inputs) == 1

    async def test_file_tools_work_without_approval(self, client, tmp_path):
        session = CodeChannelSession(channel_id="C_CODE", workdir=str(tmp_path))
        deps = AgentDeps(client=client, session=session)
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
