import importlib
import json
import subprocess
from unittest.mock import AsyncMock, Mock, patch

from agents import ToolInputGuardrailData
from agents.tool_context import ToolContext
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from agent.deps import AgentDeps, RequestDeps
from agent.guardrails import session_stopped
from agent.store import CodeChannelSession
from agent.tools import (
    archive_channel,
    clone_repo,
    create_code_channel,
    edit_file,
    list_views,
    publish_diff,
    publish_html_view,
    read_file,
    read_plan,
    remove_view,
    rename_session,
    run_command,
    set_commands,
    set_context_bar,
    write_file,
    write_plan,
)
from agent.workspace import Output

# The package exports each tool under its module's name, so patch the module itself.
clone_module = importlib.import_module("agent.tools.clone_repo")


def slack_error(error: str) -> SlackApiError:
    return SlackApiError(message=error, response={"ok": False, "error": error})


async def invoke(tool, deps: AgentDeps, **args) -> str:
    ctx = ToolContext(
        context=deps,
        tool_name=tool.name,
        tool_call_id="call_1",
        tool_arguments=json.dumps(args),
    )
    return await tool.on_invoke_tool(ctx, json.dumps(args))


def git(workdir, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(workdir), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class TestTools:
    def setup_method(self):
        self.client = Mock(AsyncWebClient)
        self.session = CodeChannelSession(channel_id="C123")
        self.deps = AgentDeps(client=self.client, session=self.session, user_id="U123")

    async def test_set_context_bar_drops_unset_fields(self):
        await invoke(
            set_context_bar,
            self.deps,
            items=[
                {
                    "key": "repo",
                    "label": "borant/billing",
                    "icon": "folder",
                    "url": "https://github.com/borant/billing",
                },
                {
                    "key": "ci",
                    "label": "Tests pending",
                    "icon": "terminal",
                    "url": None,
                },
            ],
        )

        kwargs = self.client.agents_conversations_setProperties.call_args.kwargs
        assert kwargs["channel_id"] == "C123"
        assert kwargs["code_channel"]["context_bar_items"][1] == {
            "key": "ci",
            "label": "Tests pending",
            "icon": "terminal",
        }

    async def test_write_plan_returns_why_slack_rejected_the_markdown(self):
        self.client.canvases_create.side_effect = SlackApiError(
            message="canvas_creation_failed",
            response={
                "ok": False,
                "error": "canvas_creation_failed",
                "detail": "line 11: Unsupported list type (bullet) within numbered list",
            },
        )

        result = await invoke(
            write_plan, self.deps, markdown="# Plan\n\n1. Step\n   - Sub"
        )

        assert "Unsupported list type (bullet) within numbered list" in result
        assert "call write_plan again" in result
        assert self.session.plan_canvas_id is None

    async def test_write_plan_creates_and_attaches_canvas_once(self):
        self.client.canvases_create.return_value = {"canvas_id": "F123"}

        await invoke(write_plan, self.deps, markdown="# Plan\n\n1. Read the code")

        view = self.client.agents_conversations_setView.call_args.kwargs
        assert view["type"] == "canvas"
        assert view["canvas_id"] == "F123"
        assert view["access_level"] == "comment"
        assert self.session.plan_canvas_id == "F123"

        self.client.agents_conversations_setCanvasContent.return_value = {
            "sections_changed_count": 1
        }
        result = await invoke(
            write_plan, self.deps, markdown="# Plan\n\n1. Read the code\n2. Fix it"
        )

        self.client.canvases_create.assert_called_once()
        update = self.client.agents_conversations_setCanvasContent.call_args.kwargs
        assert update == {
            "channel": "C123",
            "canvas_id": "F123",
            "content": "# Plan\n\n1. Read the code\n2. Fix it",
        }
        assert "1 sections changed" in result

    async def test_read_plan_includes_open_comments(self):
        self.session.plan_canvas_id = "F123"
        self.client.agents_conversations_getCanvas.return_value = {
            "content": "# Plan",
            "comments": [
                {
                    "user_id": "U2",
                    "text": "Billing last?",
                    "quoted_text": "1. Inventory",
                    "replies": [{"user_id": "U3", "text": "+1"}],
                }
            ],
        }

        result = await invoke(read_plan, self.deps)

        assert (
            self.client.agents_conversations_getCanvas.call_args.kwargs[
                "include_resolved"
            ]
            is False
        )
        assert "Billing last?" in result
        assert "+1" in result

    async def test_read_plan_without_a_plan_skips_the_api(self):
        assert "No plan yet" in await invoke(read_plan, self.deps)
        self.client.agents_conversations_getCanvas.assert_not_called()

    async def test_publish_html_view(self):
        self.client.agents_conversations_setView.return_value = {"view_id": "Ct1"}

        await invoke(
            publish_html_view,
            self.deps,
            view_key="reports/tests.html",
            name="Tests",
            html="<html></html>",
        )

        kwargs = self.client.agents_conversations_setView.call_args.kwargs
        assert kwargs["type"] == "html"
        assert kwargs["view_key"] == "reports/tests.html"

    async def test_list_views(self):
        self.client.agents_conversations_listViews.return_value = {
            "views": [
                {
                    "view_id": "T1",
                    "view_key": "plan",
                    "label": "Plan",
                    "content_version": 1,
                }
            ]
        }

        result = await invoke(list_views, self.deps)

        assert "1 of 5" in result
        assert "view_id=T1" in result

    async def test_remove_view(self):
        await invoke(remove_view, self.deps, view_id="T1")

        self.client.agents_conversations_removeView.assert_called_once_with(
            channel_id="C123", view_id="T1"
        )

    async def test_set_commands(self):
        self.client.agents_conversations_setCommands.return_value = {"command_count": 1}

        await invoke(
            set_commands,
            self.deps,
            commands=[
                {
                    "name": "run-tests",
                    "description": "Run the tests",
                    "argument_hint": None,
                }
            ],
        )

        kwargs = self.client.agents_conversations_setCommands.call_args.kwargs
        assert kwargs["commands"] == [
            {"name": "run-tests", "description": "Run the tests"}
        ]

    async def test_rename_session(self):
        await invoke(rename_session, self.deps, title="Fix flaky login test")

        self.client.agents_sessions_rename.assert_called_once_with(
            channel_id="C123", title="Fix flaky login test"
        )

    async def test_archive_channel_shares_the_summary(self):
        self.client.chat_postMessage.return_value = {"ts": "111.222"}

        await invoke(archive_channel, self.deps, summary="Fixed it.")

        self.client.agents_conversations_archive.assert_called_once_with(
            channel_id="C123", summary_message_ts="111.222"
        )
        assert self.session.archived is True

    async def test_archive_channel_closes_the_session_before_archiving(self):
        self.client.chat_postMessage.return_value = {"ts": "111.222"}

        await invoke(archive_channel, self.deps, summary="Fixed it.")

        calls = [name for name, _args, _kwargs in self.client.method_calls]
        assert calls == [
            "chat_postMessage",
            "agents_sessions_setStatus",
            "agents_conversations_archive",
        ]
        self.client.agents_sessions_setStatus.assert_called_once_with(
            channel_id="C123", status="closed"
        )

    async def test_archive_channel_without_origin_link_still_archives(self):
        self.client.chat_postMessage.return_value = {"ts": "111.222"}
        self.client.agents_conversations_archive.side_effect = [
            slack_error("no_origin_link"),
            {"ok": True},
        ]

        await invoke(archive_channel, self.deps, summary="Fixed it.")

        assert self.client.agents_conversations_archive.call_args.kwargs == {
            "channel_id": "C123"
        }
        assert self.session.archived is True

    async def test_create_code_channel_failure_leaves_the_request_in_place(self):
        self.client.agents_conversations_create.side_effect = slack_error(
            "missing_scope"
        )
        deps = RequestDeps(
            client=self.client,
            user_id="U123",
            channel_id="C_ORIGIN",
            message_ts="1.1",
            thread_ts="1.1",
        )

        assert "missing_scope" in await invoke(create_code_channel, deps, title="x")
        assert deps.code_channel_id is None
        self.client.chat_postMessage.assert_not_called()

    async def test_api_errors_are_returned_to_the_model(self):
        self.client.agents_sessions_rename.side_effect = slack_error("not_authorized")

        assert "not_authorized" in await invoke(rename_session, self.deps, title="x")

    async def test_stopped_session_skips_tool_calls(self):
        ctx = ToolContext(
            context=self.deps,
            tool_name="set_context_bar",
            tool_call_id="call_1",
            tool_arguments="{}",
        )
        data = ToolInputGuardrailData(context=ctx, agent=Mock())

        assert session_stopped.guardrail_function(data).behavior["type"] == "allow"
        self.session.stopped = True
        rejected = session_stopped.guardrail_function(data).behavior
        assert rejected["type"] == "reject_content"
        assert "stopped" in rejected["message"]

    async def test_clone_repo_refuses_local_paths_and_options(self):
        with patch.object(clone_module, "run") as run:
            for url in ["/etc", "file:///etc", "--upload-pack=touch x", "ext::sh"]:
                assert "Can't clone" in await invoke(
                    clone_repo, self.deps, repo_url=url
                )
        run.assert_not_called()

    async def test_clone_repo_ends_the_options_before_the_url(self):
        with patch.object(
            clone_module,
            "run",
            new=AsyncMock(
                return_value=Output(returncode=0, stdout="main\n", stderr="")
            ),
        ) as run:
            await invoke(clone_repo, self.deps, repo_url="https://example.com/repo.git")

        clone = run.call_args_list[0].args
        assert clone[clone.index("--") + 1] == "https://example.com/repo.git"
        assert clone[clone.index("--config") + 1] == "core.symlinks=false"

    async def test_cloning_again_replaces_the_earlier_clone(self, tmp_path):
        earlier = tmp_path / "earlier"
        earlier.mkdir()
        self.session.workdir = str(earlier)
        with patch.object(
            clone_module,
            "run",
            new=AsyncMock(
                return_value=Output(returncode=0, stdout="main\n", stderr="")
            ),
        ):
            await invoke(clone_repo, self.deps, repo_url="https://example.com/repo.git")

        assert not earlier.exists()
        assert self.session.workdir != str(earlier)

    async def test_publish_diff_includes_commits_on_the_default_branch_and_new_files(
        self, tmp_path
    ):
        git(tmp_path, "init", "-q", "-b", "main")
        (tmp_path / "README.md").write_text("hello\n")
        git(tmp_path, "add", ".")
        git(
            tmp_path,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-qm",
            "init",
        )
        self.session.workdir = str(tmp_path)
        self.session.base_branch = "main"
        self.session.base_commit = git(tmp_path, "rev-parse", "HEAD")
        # A commit straight onto main, plus a file git doesn't track yet.
        (tmp_path / "README.md").write_text("hello world\n")
        git(
            tmp_path,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-qam",
            "edit",
        )
        (tmp_path / "NEW.md").write_text("new\n")

        await invoke(publish_diff, self.deps)

        content = self.client.agents_conversations_setView.call_args.kwargs["content"]
        assert "+hello world" in content
        assert "+++ b/NEW.md" in content
        assert "+new" in content

    async def test_read_file_reads_a_range_of_lines(self, tmp_path):
        (tmp_path / "notes.txt").write_text("one\ntwo\nthree\n")
        self.session.workdir = str(tmp_path)

        result = await invoke(
            read_file, self.deps, path="notes.txt", start_line=2, end_line=3
        )

        assert result == "notes.txt (lines 2–3 of 3):\ntwo\nthree"

    async def test_file_tools_stay_inside_the_clone(self, tmp_path):
        clone = tmp_path / "clone"
        (clone / ".git").mkdir(parents=True)
        (tmp_path / "secret.txt").write_text("secret")
        self.session.workdir = str(clone)

        read = await invoke(
            read_file, self.deps, path="../secret.txt", start_line=None, end_line=None
        )
        wrote = await invoke(write_file, self.deps, path="/tmp/x", content="x")
        hooked = await invoke(
            write_file, self.deps, path=".git/hooks/pre-commit", content="x"
        )

        assert "outside the repository" in read
        assert "outside the repository" in wrote
        assert "inside `.git`" in hooked
        assert not (clone / ".git" / "hooks").exists()

    async def test_write_file_creates_parent_directories(self, tmp_path):
        self.session.workdir = str(tmp_path)

        await invoke(write_file, self.deps, path="src/app/main.py", content="x = 1\n")

        assert (tmp_path / "src" / "app" / "main.py").read_text() == "x = 1\n"

    async def test_edit_file_replaces_text_that_appears_once(self, tmp_path):
        (tmp_path / "app.py").write_text("a = 1\nb = 1\n")
        self.session.workdir = str(tmp_path)

        missing = await invoke(
            edit_file, self.deps, path="app.py", old_text="c = 1", new_text="c = 2"
        )
        twice = await invoke(
            edit_file, self.deps, path="app.py", old_text=" = 1", new_text=" = 2"
        )
        once = await invoke(
            edit_file, self.deps, path="app.py", old_text="b = 1", new_text="b = 2"
        )

        assert "Didn't find" in missing
        assert "2 times" in twice
        assert once == "Edited app.py."
        assert (tmp_path / "app.py").read_text() == "a = 1\nb = 2\n"

    async def test_run_command_keeps_the_end_of_long_output(self, tmp_path):
        self.session.workdir = str(tmp_path)

        result = await invoke(
            run_command,
            self.deps,
            command="python3 -c \"print('x' * 10000); print('3 failed, 9 passed')\"",
        )

        assert "characters cut" in result
        assert "3 failed, 9 passed" in result

    async def test_run_command_hides_the_app_secrets(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp-test")
        self.session.workdir = str(tmp_path)

        result = await invoke(run_command, self.deps, command="env")

        assert "PATH=" in result
        for secret in ("sk-test", "xoxb-test", "ghp-test"):
            assert secret not in result

    async def test_run_command_passes_shell_syntax_to_the_program_as_text(
        self, tmp_path
    ):
        self.session.workdir = str(tmp_path)

        result = await invoke(
            run_command, self.deps, command="ls && touch made", directory=None
        )

        assert "exit=" in result
        assert not (tmp_path / "made").exists()

    async def test_run_command_runs_in_a_directory_inside_the_clone(self, tmp_path):
        (tmp_path / "packages" / "web").mkdir(parents=True)
        (tmp_path / "packages" / "web" / "package.json").write_text("{}")
        self.session.workdir = str(tmp_path / "")

        inside = await invoke(
            run_command, self.deps, command="ls", directory="packages/web"
        )
        outside = await invoke(run_command, self.deps, command="ls", directory="..")

        assert "package.json" in inside
        assert "not a directory in the repository" in outside

    async def test_run_command_explains_a_missing_program(self, tmp_path):
        self.session.workdir = str(tmp_path)

        result = await invoke(
            run_command, self.deps, command="no-such-program --help", directory=None
        )

        assert result == "no-such-program isn't installed here."
