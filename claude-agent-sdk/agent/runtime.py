"""What the tools and hooks share during a run: its deps, and the shape of a tool result.

The Claude Agent SDK calls a tool with only its arguments, so `agent/agent.py`
sets the run's deps here before each run starts, and the tools and the hooks in
`agent/guardrails.py` read them back.
"""

from contextvars import ContextVar

from agent.sessions import AgentDeps, RequestDeps

current_deps: ContextVar[AgentDeps | RequestDeps] = ContextVar("current_deps")


def tool_result(text: str) -> dict:
    """A tool's reply to the model."""
    return {"content": [{"type": "text", "text": text}]}
