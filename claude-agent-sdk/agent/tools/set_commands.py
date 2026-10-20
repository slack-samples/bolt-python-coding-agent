from claude_agent_sdk import tool
from slack_sdk.errors import SlackApiError

from agent.runtime import current_deps, tool_result

DESCRIPTION = """\
Register the slash commands people can use in this code channel.

Offer shortcuts for things you'll do often in this task, like `run-tests`, \
`summarize`, or `wrap-up`. When someone runs one, you'll receive it as a \
message like `/run-tests <text>`. The list replaces your current set; send an \
empty list to clear it. Register commands once early and only update them when \
the useful set changes.\
"""

COMMAND = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "The command name without a leading slash, such as `run-tests`. 1–31 characters.",
        },
        "description": {
            "type": "string",
            "description": "What the command does, shown in the composer typeahead.",
        },
        "argument_hint": {
            "type": "string",
            "description": "A hint for the command's arguments, such as `[title]`.",
        },
    },
    "required": ["name", "description"],
}


@tool(
    "set_commands",
    DESCRIPTION,
    {
        "type": "object",
        "properties": {
            "commands": {
                "type": "array",
                "items": COMMAND,
                "description": "The full set of commands to offer.",
            },
        },
        "required": ["commands"],
    },
)
async def set_commands(args: dict) -> dict:
    commands = args["commands"]
    deps = current_deps.get()
    try:
        response = await deps.client.agents_conversations_setCommands(
            channel_id=deps.channel_id,
            commands=commands,
        )
        return tool_result(
            f"Registered {response.get('command_count', len(commands))} commands."
        )
    except SlackApiError as e:
        return tool_result(f"Could not register commands: {e.response['error']}")
