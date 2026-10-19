from pydantic_ai import RunContext

from agent.sessions import AgentDeps
from agent.workspace import resolve_path


async def write_file(ctx: RunContext[AgentDeps], path: str, content: str) -> str:
    """Create a file in the cloned repository, or replace one with new content.

    Use it for new files or full rewrites. To change part of an existing file,
    use `edit_file`. Files under `.git` can't be written.

    Args:
        path: The file's path relative to the repository root, such as `src/app.py`.
        content: The complete new contents of the file.
    """
    session = ctx.deps.session
    if not session.workdir:
        return "No working directory yet — call clone_repo first."
    target = resolve_path(session.workdir, path, writing=True)
    if target is None:
        return f"Can't write {path}: it's outside the repository or inside `.git`."

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"Wrote {path} ({len(content.splitlines())} lines)."
