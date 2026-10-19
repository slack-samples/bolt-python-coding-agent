"""A stand-in model that returns scripted responses, so tests can drive real agent runs."""

from collections.abc import Callable

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


def call(name: str, **arguments) -> ToolCallPart:
    """A response that calls the tool `name` with `arguments`."""
    return ToolCallPart(tool_name=name, args=arguments)


def say(text: str) -> TextPart:
    """A response that ends the turn with `text`."""
    return TextPart(content=text)


class FakeModel(FunctionModel):
    """Answers each model call with `script(call_number)`, counting from 1."""

    def __init__(self, script: Callable[[int], object]):
        self.script = script
        self.inputs: list[list[ModelMessage]] = []
        super().__init__(self._respond)

    def _respond(self, messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        self.inputs.append(messages)
        return ModelResponse(parts=[self.script(len(self.inputs))])
