from slack_bolt.context.async_context import AsyncBoltContext
from slack_sdk.models.blocks import MarkdownTextObject, SectionBlock
from slack_sdk.models.views import View
from slack_sdk.web.async_client import AsyncWebClient


async def handle_app_home_opened(
    client: AsyncWebClient, context: AsyncBoltContext, event: dict
):
    """Publish a short Home tab that explains how to start a task.

    Under agent_view this event also fires for the Messages tab, which needs no
    view since messages there are answered like mentions.
    """
    if event.get("tab") != "home":
        return

    await client.views_publish(
        user_id=context.user_id,
        view=View(
            type="home",
            blocks=[
                SectionBlock(
                    text=MarkdownTextObject(
                        text=(
                            "Message me here, or mention me in a channel, with a coding "
                            "task and a repo. I'll answer quick questions in place and "
                            "create a code channel for anything that takes more than "
                            "one message."
                        ),
                    ),
                ),
            ],
        ),
    )
