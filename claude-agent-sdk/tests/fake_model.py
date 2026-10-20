"""A stand-in model that returns scripted responses, so tests can drive real agent runs.

The SDK runs the Claude Code CLI, which calls the Anthropic Messages API at
`ANTHROPIC_BASE_URL`. `FakeModel` serves that API on localhost and answers
each call from a script, so the real SDK and CLI run without calling Anthropic.
"""

import itertools
import json
import os
import shutil
from collections.abc import Callable
from tempfile import mkdtemp
from unittest.mock import patch

from aiohttp import web

_ids = itertools.count()

# The prefix the CLI gives the agent's tools, from its MCP server's name.
TOOL_PREFIX = "mcp__coding-agent__"


def call(name: str, **arguments) -> dict:
    """A response that calls the tool `name` with `arguments`."""
    return {
        "type": "tool_use",
        "id": f"toolu_{next(_ids)}",
        "name": TOOL_PREFIX + name,
        "input": arguments,
    }


def say(text: str) -> dict:
    """A response that ends the turn with `text`."""
    return {"type": "text", "text": text}


def _events(block: dict, model: str) -> list[dict]:
    """The stream of events the Messages API sends for a response of one block."""
    if block["type"] == "tool_use":
        start = {**block, "input": {}}
        delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        stop_reason = "tool_use"
    else:
        start = {"type": "text", "text": ""}
        delta = {"type": "text_delta", "text": block["text"]}
        stop_reason = "end_turn"
    message = {
        "id": f"msg_{next(_ids)}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    return [
        {"type": "message_start", "message": message},
        {"type": "content_block_start", "index": 0, "content_block": start},
        {"type": "content_block_delta", "index": 0, "delta": delta},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": 1},
        },
        {"type": "message_stop"},
    ]


class FakeModel:
    """Answers each model call with `script(call_number)`, counting from 1.

    Inside `async with FakeModel(script)`, every run the SDK starts calls this
    model. The CLI keeps its sessions in a temp directory, not `~/.claude`.
    """

    def __init__(self, script: Callable[[int], dict]):
        self.script = script
        # The messages sent with each scripted call.
        self.inputs: list[list[dict]] = []

    async def _messages(self, request: web.Request) -> web.StreamResponse:
        body = await request.json()
        tools = [tool["name"] for tool in body.get("tools", [])]
        if any(name.startswith(TOOL_PREFIX) for name in tools):
            self.inputs.append(body["messages"])
            block = self.script(len(self.inputs))
        else:
            # A call the CLI makes for itself, like titling the session.
            block = say("ok")
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for event in _events(block, body.get("model", "")):
            await response.write(
                f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()
            )
        await response.write_eof()
        return response

    async def __aenter__(self):
        app = web.Application()
        app.router.add_post("/v1/messages", self._messages)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]

        self._config_dir = mkdtemp(prefix="claude-config-")
        # Drop any provider or CLI settings from the environment running the
        # tests, like Bedrock, so the CLI only ever reaches this model.
        env = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith(("ANTHROPIC_", "CLAUDE_"))
        }
        env.update(
            ANTHROPIC_API_KEY="test",
            ANTHROPIC_BASE_URL=f"http://127.0.0.1:{port}",
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
            CLAUDE_CONFIG_DIR=self._config_dir,
        )
        self._env = patch.dict(os.environ, env, clear=True)
        self._env.start()
        return self

    async def __aexit__(self, *_exc) -> None:
        self._env.stop()
        await self._runner.cleanup()
        shutil.rmtree(self._config_dir, ignore_errors=True)
