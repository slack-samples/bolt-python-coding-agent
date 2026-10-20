from claude_agent_sdk import tool

from agent.sessions import current_deps
from agent.tools import tool_result
from agent.workspace import resolve_path

DESCRIPTION = """\
Replace one exact piece of text in a file in the cloned repository.

`old_text` must appear exactly once in the file, including its whitespace \
and indentation, so include enough surrounding lines to make it unique. Read \
the file with `read_file` first. Files under `.git` can't be edited.\
"""


@tool(
    "edit_file",
    DESCRIPTION,
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The file's path relative to the repository root, such as `src/app.py`.",
            },
            "old_text": {
                "type": "string",
                "description": "The exact text to replace.",
            },
            "new_text": {
                "type": "string",
                "description": "The text to put in its place.",
            },
        },
        "required": ["path", "old_text", "new_text"],
    },
)
async def edit_file(args: dict) -> dict:
    path, old_text, new_text = args["path"], args["old_text"], args["new_text"]
    session = current_deps.get().session
    if not session.workdir:
        return tool_result("No working directory yet — call clone_repo first.")
    target = resolve_path(session.workdir, path, writing=True)
    if target is None:
        return tool_result(
            f"Can't edit {path}: it's outside the repository or inside `.git`."
        )
    if not target.is_file():
        return tool_result(f"No file at {path}. Create it with write_file.")

    content = target.read_text()
    count = content.count(old_text)
    if count == 0:
        return tool_result(
            f"Didn't find old_text in {path}. Read the file and copy the text exactly."
        )
    if count > 1:
        return tool_result(
            f"old_text appears {count} times in {path}. Include more surrounding lines."
        )
    target.write_text(content.replace(old_text, new_text, 1))
    return tool_result(f"Edited {path}.")
