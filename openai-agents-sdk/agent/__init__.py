"""The agent package, and the only thing listeners import from.

Listeners call these and nothing from the agent framework, so `listeners/` reads
the same whichever framework runs the agent:

- `answer_request` — reply to a mention outside a code channel, or create one.
- `run_turn` — run a message or slash command in a code channel as a turn.
- `resume_turn` — continue a turn paused on a command approval.
- `stop_turn` — handle the native stop button.
- `end_session` — forget an archived code channel.
"""

from .agent import answer_request
from .deps import RequestDeps
from .store import CodeChannelSession, session_store
from .turns import end_session, resume_turn, run_turn, stop_turn

__all__ = [
    "CodeChannelSession",
    "RequestDeps",
    "answer_request",
    "end_session",
    "resume_turn",
    "run_turn",
    "session_store",
    "stop_turn",
]
