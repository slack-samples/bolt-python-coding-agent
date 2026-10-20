from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import RunContext
from slack_sdk.errors import SlackApiError

from agent.sessions import AgentDeps


class ContextBarItem(BaseModel):
    key: str = Field(
        description="A unique key for the item, such as `repo`, `branch`, `pr`, or `ci`."
    )
    label: str = Field(
        description="The display text, such as `PR #42 is open` or `Tests passing`."
    )
    icon: (
        Literal[
            "branch",
            "folder",
            "hierarchy",
            "life-ring",
            "link",
            "globe",
            "terminal",
            "code",
            "search",
            "lock",
        ]
        | None
    ) = Field(description="An icon shown beside the label.")
    url: str | None = Field(description="Makes the item a link to this URL.")


async def set_context_bar(
    ctx: RunContext[AgentDeps],
    items: list[ContextBarItem],
) -> str:
    """Set the items pinned to the context bar at the top of the code channel.

    Use it to show where the work stands: the repo, branch, PR, and CI status.
    The list replaces the current set, so always send every item you want to
    keep. Keep labels current as things change. At most 5 items.

    Args:
        items: The full set of context bar items, in display order.
    """
    deps = ctx.deps
    try:
        await deps.client.agents_conversations_setProperties(
            channel_id=deps.channel_id,
            code_channel={
                "context_bar_items": [
                    item.model_dump(exclude_none=True) for item in items[:5]
                ],
            },
        )
        return f"Set {min(len(items), 5)} context bar items."
    except SlackApiError as e:
        return f"Could not set the context bar: {e.response['error']}"
