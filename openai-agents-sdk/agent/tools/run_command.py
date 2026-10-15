"""⚠️ SECURITY: `run_command` runs programs chosen by the language model on the
machine running this app. Read-only commands and local git changes run right
away, and anything else needs human approval in Slack first (see
`agent/approvals.py`) — only ever run this against trusted, throwaway
repositories in the session temp directory. See the README's Command approvals
section.
"""

import asyncio
import shlex
from pathlib import Path

from agents import function_tool
from agents.run_context import RunContextWrapper

from agent.deps import AgentDeps
from agent.guardrails import run_command_needs_approval, session_stopped
from agent.workspace import clip, resolve_path, run

# Cap any single command so a hung/looping command can't wedge the session.
COMMAND_TIMEOUT_SECONDS = 120


@function_tool(
    needs_approval=run_command_needs_approval,
    tool_input_guardrails=[session_stopped],
)
async def run_command(
    wrapper: RunContextWrapper[AgentDeps],
    command: str,
    directory: str | None = None,
) -> str:
    """Run one program in the cloned repository and return its output.

    Use it to search, build, test, and run git, like `pytest -q` or `git status`.
    The program runs directly, without a shell, so pipes, `&&`, redirects, globs,
    and variables don't work: run one program at a time, and use `directory`
    instead of `cd`. Use `read_file`, `write_file`, and `edit_file` for files.
    Read-only commands and local git changes like `git add`, `git commit`, and
    `git switch -c` run immediately; anything else, including tests and builds,
    asks the user to approve it in Slack before running.

    Args:
        command: The program and its arguments, such as `pytest -q tests/test_app.py`.
        directory: A directory in the repository to run in, such as `packages/web`, or omit it for the repository root.
    """
    session = wrapper.context.session
    if not session.workdir or not Path(session.workdir).is_dir():
        return "No working directory yet — call clone_repo first."
    cwd = resolve_path(session.workdir, directory or ".")
    if cwd is None or not cwd.is_dir():
        return f"Can't run in {directory}: it's not a directory in the repository."
    try:
        args = shlex.split(command)
    except ValueError as e:
        return f"Couldn't read the command: {e}."
    if not args:
        return "No command given."

    try:
        result = await run(*args, cwd=str(cwd), timeout=COMMAND_TIMEOUT_SECONDS)
    except FileNotFoundError:
        return f"{args[0]} isn't installed here."
    except asyncio.TimeoutError:
        return f"Command timed out after {COMMAND_TIMEOUT_SECONDS}s: {command}"

    out = result.stdout.strip()
    err = result.stderr.strip()
    parts = [f"exit={result.returncode}"]
    if out:
        parts.append(f"stdout:\n{clip(out, 4000)}")
    if err:
        parts.append(f"stderr:\n{clip(err, 2000)}")
    return "\n".join(parts)
