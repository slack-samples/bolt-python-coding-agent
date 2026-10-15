from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunOutcome:
    """The result of a (possibly paused) agent run.

    `start_run` and `resume_run` in `agent/agent.py` return this and
    `agent/turns.py` reads it, so turn handling never touches the agent
    framework. At most one of `final_output` or `paused` is set, and neither is
    after the agent archives the channel:

    - `final_output` — the run completed; this is the text to post.
    - `paused` + `command` — the run paused on a command that needs approval.
      `paused` is the handle on the run, passed back to `resume_run` unchanged
      once someone decides.
    """

    final_output: str | None = None
    paused: Any = None
    # The command waiting on approval, shown on the approval message.
    command: str | None = None
    # Always set — the conversation so far, persisted so the next turn has context.
    history: list = field(default_factory=list)

    @property
    def needs_approval(self) -> bool:
        return self.paused is not None
