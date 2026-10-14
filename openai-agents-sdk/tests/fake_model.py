"""A stand-in model that returns scripted responses, so tests can drive real agent runs."""

import itertools
import json
from collections.abc import Callable

from agents import Usage
from agents.items import ModelResponse
from agents.models.interface import Model
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

_ids = itertools.count()


def call(name: str, **arguments) -> ResponseFunctionToolCall:
    """A response that calls the tool `name` with `arguments`."""
    return ResponseFunctionToolCall(
        type="function_call",
        id=f"fc_{next(_ids)}",
        call_id=f"call_{next(_ids)}",
        name=name,
        arguments=json.dumps(arguments),
        status="completed",
    )


def say(text: str) -> ResponseOutputMessage:
    """A response that ends the turn with `text`."""
    return ResponseOutputMessage(
        type="message",
        id=f"msg_{next(_ids)}",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )


class FakeModel(Model):
    """Answers each model call with `script(call_number)`, counting from 1."""

    def __init__(self, script: Callable[[int], object]):
        self.script = script
        self.inputs: list = []

    async def get_response(self, system_instructions, input, *args, **kwargs):
        self.inputs.append(input)
        output = self.script(len(self.inputs))
        return ModelResponse(output=[output], usage=Usage(), response_id=None)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError
