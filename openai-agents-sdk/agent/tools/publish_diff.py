import subprocess
from pathlib import Path

from agents import function_tool
from agents.run_context import RunContextWrapper
from slack_sdk.errors import SlackApiError

from agent.deps import AgentDeps
from agent.guardrails import session_stopped


def _git(workdir: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )


@function_tool(tool_input_guardrails=[session_stopped])
def publish_diff(wrapper: RunContextWrapper[AgentDeps]) -> str:
    """Publish the work so far as a diff in the code channel's code tab.

    The diff covers everything changed since the repository was cloned —
    committed, uncommitted, and new files. Call this after making changes so the
    user can review the work. Safe to call repeatedly — each call replaces the
    code tab content.
    """
    deps = wrapper.context
    session = deps.session
    if not session.workdir or not Path(session.workdir).is_dir():
        return "No working directory yet — call clone_repo first."

    # Diff against the commit that was cloned, not the branch name, so commits
    # made straight onto the default branch still show.
    diff = _git(session.workdir, "diff", session.base_commit or "HEAD")
    if diff.returncode != 0:
        return f"git diff failed: {diff.stderr.strip()[:1000]}"
    content = diff.stdout

    # `git diff` leaves out files git doesn't track yet, so add each new file.
    untracked = _git(
        session.workdir, "ls-files", "--others", "--exclude-standard", "-z"
    )
    for path in filter(None, untracked.stdout.split("\0")):
        # Exits 1 when the files differ, which they always do here.
        content += _git(
            session.workdir, "diff", "--no-index", "--", "/dev/null", path
        ).stdout

    if not content.strip():
        return "No changes to publish yet — the working tree matches the clone."

    head = _git(session.workdir, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    try:
        deps.client.agents_conversations_setView(
            channel_id=deps.channel_id,
            type="diff",
            content=content,
            base_branch=session.base_branch,
            head_branch=head,
        )
        return f"Published the diff ({session.base_branch}...{head}) to the code tab."
    except SlackApiError as e:
        return f"Could not publish the diff: {e.response['error']}"
