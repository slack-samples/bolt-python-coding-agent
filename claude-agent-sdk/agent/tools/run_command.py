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

from claude_agent_sdk import tool

from agent.runtime import current_deps, tool_result
from agent.workspace import clip, resolve_path, run

# Cap any single command so a hung/looping command can't wedge the session.
COMMAND_TIMEOUT_SECONDS = 120

DESCRIPTION = """\
Run one program in the cloned repository and return its output.

Use it to search, build, test, and run git, like `pytest -q` or `git status`. \
The program runs directly, without a shell, so pipes, `&&`, redirects, globs, \
and variables don't work: run one program at a time, and use `directory` \
instead of `cd`. Use `read_file`, `write_file`, and `edit_file` for files. \
Read-only commands and local git changes like `git add`, `git commit`, and \
`git switch -c` run immediately; anything else, including tests and builds, \
asks the user to approve it in Slack before running.\
"""


# The PreToolUse hook in `agent/guardrails.py` asks for approval before this runs.
@tool(
    "run_command",
    DESCRIPTION,
    {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The program and its arguments, such as `pytest -q tests/test_app.py`.",
            },
            "directory": {
                "type": "string",
                "description": "A directory in the repository to run in, such as `packages/web`, or omit it for the repository root.",
            },
        },
        "required": ["command"],
    },
)
async def run_command(args: dict) -> dict:
    command, directory = args["command"], args.get("directory")
    session = current_deps.get().session
    if not session.workdir or not Path(session.workdir).is_dir():
        return tool_result("No working directory yet — call clone_repo first.")
    cwd = resolve_path(session.workdir, directory or ".")
    if cwd is None or not cwd.is_dir():
        return tool_result(
            f"Can't run in {directory}: it's not a directory in the repository."
        )
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return tool_result(f"Couldn't read the command: {e}.")
    if not argv:
        return tool_result("No command given.")

    try:
        result = await run(*argv, cwd=str(cwd), timeout=COMMAND_TIMEOUT_SECONDS)
    except FileNotFoundError:
        return tool_result(f"{argv[0]} isn't installed here.")
    except asyncio.TimeoutError:
        return tool_result(
            f"Command timed out after {COMMAND_TIMEOUT_SECONDS}s: {command}"
        )

    out = result.stdout.strip()
    err = result.stderr.strip()
    parts = [f"exit={result.returncode}"]
    if out:
        parts.append(f"stdout:\n{clip(out, 4000)}")
    if err:
        parts.append(f"stderr:\n{clip(err, 2000)}")
    return tool_result("\n".join(parts))
