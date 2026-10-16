from pathlib import Path

from agents import function_tool
from agents.run_context import RunContextWrapper
from slack_sdk.errors import SlackApiError

from agent.guardrails import session_stopped
from agent.sessions import AgentDeps
from agent.workspace import run


@function_tool(tool_input_guardrails=[session_stopped])
async def publish_diff(wrapper: RunContextWrapper[AgentDeps]) -> str:
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
    diff = await run("git", "diff", session.base_commit or "HEAD", cwd=session.workdir)
    if diff.returncode != 0:
        return f"git diff failed: {diff.stderr.strip()[:1000]}"
    content = diff.stdout

    # `git diff` leaves out files git doesn't track yet, so add each new file.
    untracked = await run(
        "git", "ls-files", "--others", "--exclude-standard", "-z", cwd=session.workdir
    )
    for path in filter(None, untracked.stdout.split("\0")):
        # Exits 1 when the files differ, which they always do here.
        new_file = await run(
            "git", "diff", "--no-index", "--", "/dev/null", path, cwd=session.workdir
        )
        content += new_file.stdout

    if not content.strip():
        return "No changes to publish yet — the working tree matches the clone."

    head = await run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=session.workdir)
    branch = head.stdout.strip()
    try:
        await deps.client.agents_conversations_setView(
            channel_id=deps.channel_id,
            type="diff",
            content=content,
            base_branch=session.base_branch,
            head_branch=branch,
        )
        return f"Published the diff ({session.base_branch}...{branch}) to the code tab."
    except SlackApiError as e:
        return f"Could not publish the diff: {e.response['error']}"
