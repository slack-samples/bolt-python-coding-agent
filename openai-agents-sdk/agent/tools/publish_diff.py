import subprocess
from pathlib import Path

from agents import function_tool
from agents.run_context import RunContextWrapper
from slack_sdk.errors import SlackApiError

from agent.deps import AgentDeps


@function_tool
def publish_diff(wrapper: RunContextWrapper[AgentDeps]) -> str:
    """Publish the work so far as a diff in the code channel's code tab.

    The diff covers everything changed since the default branch, committed or
    not. Call this after making changes so the user can review the work. Safe to
    call repeatedly — each call replaces the code tab content.
    """
    deps = wrapper.context
    session = deps.session
    if not session.workdir or not Path(session.workdir).is_dir():
        return "No working directory yet — call clone_repo first."

    diff = subprocess.run(
        ["git", "diff", session.base_branch or "HEAD"],
        cwd=session.workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    head = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=session.workdir,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if diff.returncode != 0:
        return f"git diff failed: {diff.stderr.strip()[:1000]}"
    if not diff.stdout.strip():
        return (
            "No changes to publish yet — the working tree matches the default branch."
        )

    try:
        deps.client.agents_conversations_setView(
            channel_id=deps.channel_id,
            type="diff",
            content=diff.stdout,
            base_branch=session.base_branch,
            head_branch=head,
        )
        return f"Published the diff ({session.base_branch}...{head}) to the code tab."
    except SlackApiError as e:
        return f"Could not publish the diff: {e.response['error']}"
