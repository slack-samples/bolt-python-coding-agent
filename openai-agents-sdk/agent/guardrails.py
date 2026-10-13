from agents import (
    ToolGuardrailFunctionOutput,
    ToolInputGuardrailData,
    tool_input_guardrail,
)


@tool_input_guardrail
def session_stopped(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
    """Skip every tool call once someone presses the stop button.

    Each code channel tool lists this guardrail, so a stopped turn changes nothing
    more in the repo or the channel while the model wraps up.
    """
    if data.context.context.session.stopped:
        return ToolGuardrailFunctionOutput.reject_content(
            "The user stopped this session. Don't call any more tools. "
            "Reply with one short line saying you've stopped."
        )
    return ToolGuardrailFunctionOutput.allow()
