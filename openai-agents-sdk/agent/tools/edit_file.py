from agents import function_tool
from agents.run_context import RunContextWrapper

from agent.deps import AgentDeps
from agent.guardrails import session_stopped
from agent.workspace import resolve_path


@function_tool(tool_input_guardrails=[session_stopped])
async def edit_file(
    wrapper: RunContextWrapper[AgentDeps], path: str, old_text: str, new_text: str
) -> str:
    """Replace one exact piece of text in a file in the cloned repository.

    `old_text` must appear exactly once in the file, including its whitespace
    and indentation, so include enough surrounding lines to make it unique. Read
    the file with `read_file` first. Files under `.git` can't be edited.

    Args:
        path: The file's path relative to the repository root, such as `src/app.py`.
        old_text: The exact text to replace.
        new_text: The text to put in its place.
    """
    session = wrapper.context.session
    if not session.workdir:
        return "No working directory yet — call clone_repo first."
    target = resolve_path(session.workdir, path, writing=True)
    if target is None:
        return f"Can't edit {path}: it's outside the repository or inside `.git`."
    if not target.is_file():
        return f"No file at {path}. Create it with write_file."

    content = target.read_text()
    count = content.count(old_text)
    if count == 0:
        return (
            f"Didn't find old_text in {path}. Read the file and copy the text exactly."
        )
    if count > 1:
        return (
            f"old_text appears {count} times in {path}. Include more surrounding lines."
        )
    target.write_text(content.replace(old_text, new_text, 1))
    return f"Edited {path}."
