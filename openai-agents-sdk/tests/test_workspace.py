import json
import sys

from agent.workspace import clip, resolve_path, run


class TestWorkspace:
    async def test_run_drops_secrets_and_keeps_the_rest(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENAI_API_KEY", "x")
        monkeypatch.setenv("SLACK_APP_TOKEN", "x")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
        monkeypatch.setenv("DB_PASSWORD", "x")
        monkeypatch.setenv("JAVA_HOME", "/opt/java")

        result = await run(
            sys.executable,
            "-c",
            "import json, os; print(json.dumps(dict(os.environ)))",
            cwd=str(tmp_path),
        )

        env = json.loads(result.stdout)
        for name in (
            "OPENAI_API_KEY",
            "SLACK_APP_TOKEN",
            "AWS_SECRET_ACCESS_KEY",
            "DB_PASSWORD",
        ):
            assert name not in env
        assert env["JAVA_HOME"] == "/opt/java"
        assert env["GIT_TERMINAL_PROMPT"] == "0"

    def test_resolve_path_keeps_paths_inside_the_workdir(self, tmp_path):
        assert (
            resolve_path(str(tmp_path), "src/app.py")
            == tmp_path.resolve() / "src/app.py"
        )
        assert resolve_path(str(tmp_path), "../outside") is None
        assert resolve_path(str(tmp_path), "/etc/passwd") is None

    def test_resolve_path_refuses_writes_into_git(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assert resolve_path(str(tmp_path), ".git/config") is not None
        for path in [
            ".git/config",
            "src/.git/x",
            ".GIT/config",
            ".Git/hooks/x",
            ".git./x",
        ]:
            assert resolve_path(str(tmp_path), path, writing=True) is None, path
        assert resolve_path(str(tmp_path), "src/git/x", writing=True) is not None

    def test_clip_keeps_short_text_and_the_end_of_long_text(self):
        assert clip("short", 100) == "short"
        clipped = clip("a" * 1000 + "END", 100)
        assert clipped.startswith("a" * 25)
        assert clipped.endswith("END")
        assert "characters cut" in clipped
