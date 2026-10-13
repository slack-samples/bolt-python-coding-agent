from agents import function_tool
from agents.run_context import RunContextWrapper
from pydantic import BaseModel, Field
from slack_sdk.errors import SlackApiError

from agent.deps import AgentDeps
from agent.guardrails import session_stopped


class Command(BaseModel):
    name: str = Field(
        description="The command name without a leading slash, such as `run-tests`. 1–31 characters."
    )
    description: str = Field(
        description="What the command does, shown in the composer typeahead."
    )
    argument_hint: str | None = Field(
        description="A hint for the command's arguments, such as `[title]`."
    )


@function_tool(tool_input_guardrails=[session_stopped])
def set_commands(
    wrapper: RunContextWrapper[AgentDeps],
    commands: list[Command],
) -> str:
    """Register the slash commands people can use in this code channel.

    Offer shortcuts for things you'll do often in this task, like `run-tests`,
    `summarize`, or `wrap-up`. When someone runs one, you'll receive it as a
    message like `/run-tests <text>`. The list replaces your current set; send an
    empty list to clear it. Register commands once early and only update them when
    the useful set changes.

    Args:
        commands: The full set of commands to offer.
    """
    deps = wrapper.context
    try:
        response = deps.client.agents_conversations_setCommands(
            channel_id=deps.channel_id,
            commands=[command.model_dump(exclude_none=True) for command in commands],
        )
        return f"Registered {response.get('command_count', len(commands))} commands."
    except SlackApiError as e:
        return f"Could not register commands: {e.response['error']}"
