from pydantic_ai import RunContext
from slack_sdk.errors import SlackApiError

from agent.sessions import AgentDeps

PLAN_VIEW_KEY = "plan"


async def write_plan(ctx: RunContext[AgentDeps], markdown: str) -> str:
    """Write the task plan to the code channel's Plan tab.

    The plan is a canvas everyone in the channel can read and comment on, but
    only you edit. Send the whole plan as markdown each time. Sections you leave
    unchanged keep their comments. Call `read_plan` first to see feedback.

    Args:
        markdown: The full plan document as markdown, starting with a `#` title. Canvases don't support bullets nested inside a numbered list, so use a heading per step or plain numbered steps.
    """
    deps = ctx.deps
    session = deps.session
    try:
        if session.plan_canvas_id:
            response = await deps.client.agents_conversations_setCanvasContent(
                channel=deps.channel_id,
                canvas_id=session.plan_canvas_id,
                content=markdown,
            )
            return f"Updated the plan ({response.get('sections_changed_count', 0)} sections changed)."

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
        return "Created the plan and attached it as the Plan tab."
    except SlackApiError as e:
        # The detail names the markdown Slack rejected, so the model can fix it and retry.
        detail = e.response.get("detail")
        if detail:
            return (
                f"Could not write the plan: {e.response['error']} ({detail}). "
                "Fix the markdown and call write_plan again."
            )
        return f"Could not write the plan: {e.response['error']}"
