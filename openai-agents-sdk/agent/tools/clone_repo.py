import subprocess
from tempfile import mkdtemp

from agents import function_tool
from agents.run_context import RunContextWrapper

from agent.deps import AgentDeps

# Cap the clone so an unreachable or huge repository can't wedge the session.
CLONE_TIMEOUT_SECONDS = 120


@function_tool
def clone_repo(wrapper: RunContextWrapper[AgentDeps], repo_url: str) -> str:
    """Clone a git repository into a fresh temp directory for this session.

    Call this once before running commands or reading files. The clone becomes
    the working directory for all later `run_command` calls and for the diff
    published to the code channel.

    Args:
        repo_url: A git-cloneable URL (https or ssh) for the repository to work on.
    """
    session = wrapper.context.session
    workdir = mkdtemp(prefix="coding-agent-")
    try:
        clone = subprocess.run(
            ["git", "clone", "--depth", "50", repo_url, workdir],
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"Clone of {repo_url} timed out after {CLONE_TIMEOUT_SECONDS}s."
    if clone.returncode != 0:
        return f"Clone failed: {clone.stderr.strip()[:1000]}"

    head = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    session.workdir = workdir
    session.repo_url = repo_url
    session.base_branch = head.stdout.strip()
    return (
        f"Cloned {repo_url} (default branch `{session.base_branch}`) into the working "
        "directory. Create a branch with `git checkout -b agent/<topic>` before editing."
    )
