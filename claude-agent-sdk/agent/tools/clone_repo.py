import asyncio
import shutil
from pathlib import Path
from tempfile import mkdtemp

from claude_agent_sdk import tool

from agent.sessions import current_deps
from agent.tools import tool_result
from agent.workspace import run

# Cap the clone so an unreachable or huge repository can't wedge the session.
CLONE_TIMEOUT_SECONDS = 120

# Remote URL forms the agent may clone. Local paths and `file://` would copy
# files off this machine, and other transports can run commands.
CLONEABLE_URL_PREFIXES = ("git@", "https://", "ssh://")

DESCRIPTION = """\
Clone a git repository into a fresh temp directory for this session.

Call this once before running commands or reading files. The clone becomes \
the working directory for all later file and command tools and for the diff \
published to the code channel. Cloning again replaces the earlier clone.\
"""


@tool(
    "clone_repo",
    DESCRIPTION,
    {
        "type": "object",
        "properties": {
            "repo_url": {
                "type": "string",
                "description": "A remote git URL for the repository to work on, starting with `https://`, `ssh://`, or `git@`.",
            },
        },
        "required": ["repo_url"],
    },
)
async def clone_repo(args: dict) -> dict:
    repo_url = args["repo_url"]
    if not repo_url.startswith(CLONEABLE_URL_PREFIXES):
        return tool_result(
            f"Can't clone {repo_url!r}. Use a remote URL that starts with "
            "`https://`, `ssh://`, or `git@`."
        )

    session = current_deps.get().session
    workdir = mkdtemp(prefix="coding-agent-")
    try:
        # The `--` keeps a URL from being read as an option like `--upload-pack`.
        # Symlinks check out as plain files, so a link in the repo can't point a
        # read-only command at a file outside the clone.
        clone = await run(
            "git",
            "clone",
            "--config",
            "core.symlinks=false",
            "--depth",
            "50",
            "--",
            repo_url,
            workdir,
            cwd=str(Path(workdir).parent),
            timeout=CLONE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        shutil.rmtree(workdir, ignore_errors=True)
        return tool_result(
            f"Clone of {repo_url} timed out after {CLONE_TIMEOUT_SECONDS}s."
        )
    if clone.returncode != 0:
        shutil.rmtree(workdir, ignore_errors=True)
        return tool_result(f"Clone failed: {clone.stderr.strip()[:1000]}")

    head = await run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=workdir)
    commit = await run("git", "rev-parse", "HEAD", cwd=workdir)
    if session.workdir:
        shutil.rmtree(session.workdir, ignore_errors=True)
    session.workdir = workdir
    session.repo_url = repo_url
    session.base_branch = head.stdout.strip()
    session.base_commit = commit.stdout.strip()
    return tool_result(
        f"Cloned {repo_url} (default branch `{session.base_branch}`) into the working "
        "directory. Create a branch with `git switch -c agent/<topic>` before editing."
    )
