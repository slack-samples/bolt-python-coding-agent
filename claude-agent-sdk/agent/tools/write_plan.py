from claude_agent_sdk import tool
from slack_sdk.errors import SlackApiError

from agent.sessions import current_deps
from agent.tools import tool_result

PLAN_VIEW_KEY = "plan"

DESCRIPTION = """\
Write the task plan to the code channel's Plan tab.

The plan is a canvas everyone in the channel can read and comment on, but \
only you edit. Send the whole plan as markdown each time. Sections you leave \
unchanged keep their comments. Call `read_plan` first to see feedback.\
"""


@tool(
    "write_plan",
    DESCRIPTION,
    {
        "type": "object",
        "properties": {
            "markdown": {
                "type": "string",
                "description": "The full plan document as markdown, starting with a `#` title. Canvases don't support bullets nested inside a numbered list, so use a heading per step or plain numbered steps.",
            },
        },
        "required": ["markdown"],
    },
)
async def write_plan(args: dict) -> dict:
    markdown = args["markdown"]
    deps = current_deps.get()
    session = deps.session
    try:
        if session.plan_canvas_id:
            response = await deps.client.agents_conversations_setCanvasContent(
                channel=deps.channel_id,
                canvas_id=session.plan_canvas_id,
                content=markdown,
            )
            return tool_result(
                f"Updated the plan ({response.get('sections_changed_count', 0)} sections changed)."
            )

        created = await deps.client.canvases_create(
            title="Plan",
            document_content={"type": "markdown", "markdown": markdown},
        )
        # Comment access keeps the agent the sole author while users leave feedback.
        await deps.client.agents_conversations_setView(
            channel_id=deps.channel_id,
            type="canvas",
            view_key=PLAN_VIEW_KEY,
            name="Plan",
            canvas_id=created["canvas_id"],
            access_level="comment",
        )
        session.plan_canvas_id = created["canvas_id"]
        return tool_result("Created the plan and attached it as the Plan tab.")
    except SlackApiError as e:
        # The detail names the markdown Slack rejected, so the model can fix it and retry.
        detail = e.response.get("detail")
        if detail:
            return tool_result(
                f"Could not write the plan: {e.response['error']} ({detail}). "
                "Fix the markdown and call write_plan again."
            )
        return tool_result(f"Could not write the plan: {e.response['error']}")
