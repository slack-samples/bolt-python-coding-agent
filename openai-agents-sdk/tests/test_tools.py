import asyncio
import json
from unittest.mock import Mock

from agents.tool_context import ToolContext
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from agent import AgentDeps, CodeChannelSession, RequestDeps
from agent.tools import (
    archive_channel,
    create_code_channel,
    list_views,
    publish_html_view,
    read_plan,
    remove_view,
    rename_session,
    set_commands,
    set_context_bar,
    write_plan,
)


def slack_error(error: str) -> SlackApiError:
    return SlackApiError(message=error, response={"ok": False, "error": error})


def invoke(tool, deps: AgentDeps, **args) -> str:
    ctx = ToolContext(
        context=deps,
        tool_name=tool.name,
        tool_call_id="call_1",
        tool_arguments=json.dumps(args),
    )
    return asyncio.run(tool.on_invoke_tool(ctx, json.dumps(args)))


class TestTools:
    def setup_method(self):
        self.client = Mock(WebClient)
        self.session = CodeChannelSession(channel_id="C123")
        self.deps = AgentDeps(client=self.client, session=self.session, user_id="U123")

    def test_set_context_bar_drops_unset_fields(self):
        invoke(
            set_context_bar,
            self.deps,
            items=[
                {
                    "key": "repo",
                    "label": "borant/billing",
                    "icon": "folder",
                    "url": "https://github.com/borant/billing",
                },
                {
                    "key": "ci",
                    "label": "Tests pending",
                    "icon": "terminal",
                    "url": None,
                },
            ],
        )

        kwargs = self.client.agents_conversations_setProperties.call_args.kwargs
        assert kwargs["channel_id"] == "C123"
        assert kwargs["code_channel"]["context_bar_items"][1] == {
            "key": "ci",
            "label": "Tests pending",
            "icon": "terminal",
        }

    def test_write_plan_returns_why_slack_rejected_the_markdown(self):
        self.client.canvases_create.side_effect = SlackApiError(
            message="canvas_creation_failed",
            response={
                "ok": False,
                "error": "canvas_creation_failed",
                "detail": "line 11: Unsupported list type (bullet) within numbered list",
            },
        )

        result = invoke(write_plan, self.deps, markdown="# Plan\n\n1. Step\n   - Sub")

        assert "Unsupported list type (bullet) within numbered list" in result
        assert "call write_plan again" in result
        assert self.session.plan_canvas_id is None

    def test_write_plan_creates_and_attaches_canvas_once(self):
        self.client.canvases_create.return_value = {"canvas_id": "F123"}

        invoke(write_plan, self.deps, markdown="# Plan\n\n1. Read the code")

        view = self.client.agents_conversations_setView.call_args.kwargs
        assert view["type"] == "canvas"
        assert view["canvas_id"] == "F123"
        assert view["access_level"] == "comment"
        assert self.session.plan_canvas_id == "F123"

        self.client.agents_conversations_setCanvasContent.return_value = {
            "sections_changed_count": 1
        }
        result = invoke(
            write_plan, self.deps, markdown="# Plan\n\n1. Read the code\n2. Fix it"
        )

        self.client.canvases_create.assert_called_once()
        update = self.client.agents_conversations_setCanvasContent.call_args.kwargs
        assert update == {
            "channel": "C123",
            "canvas_id": "F123",
            "content": "# Plan\n\n1. Read the code\n2. Fix it",
        }
        assert "1 sections changed" in result

    def test_read_plan_includes_open_comments(self):
        self.session.plan_canvas_id = "F123"
        self.client.agents_conversations_getCanvas.return_value = {
            "content": "# Plan",
            "comments": [
                {
                    "user_id": "U2",
                    "text": "Billing last?",
                    "quoted_text": "1. Inventory",
                    "replies": [{"user_id": "U3", "text": "+1"}],
                }
            ],
        }

        result = invoke(read_plan, self.deps)

        assert (
            self.client.agents_conversations_getCanvas.call_args.kwargs[
                "include_resolved"
            ]
            is False
        )
        assert "Billing last?" in result
        assert "+1" in result

    def test_read_plan_without_a_plan_skips_the_api(self):
        assert "No plan yet" in invoke(read_plan, self.deps)
        self.client.agents_conversations_getCanvas.assert_not_called()

    def test_publish_html_view(self):
        self.client.agents_conversations_setView.return_value = {"view_id": "Ct1"}

        invoke(
            publish_html_view,
            self.deps,
            view_key="reports/tests.html",
            name="Tests",
            html="<html></html>",
        )

        kwargs = self.client.agents_conversations_setView.call_args.kwargs
        assert kwargs["type"] == "html"
        assert kwargs["view_key"] == "reports/tests.html"

    def test_list_views(self):
        self.client.agents_conversations_listViews.return_value = {
            "views": [
                {
                    "view_id": "T1",
                    "view_key": "plan",
                    "label": "Plan",
                    "content_version": 1,
                }
            ]
        }

        result = invoke(list_views, self.deps)

        assert "1 of 5" in result
        assert "view_id=T1" in result

    def test_remove_view(self):
        invoke(remove_view, self.deps, view_id="T1")

        self.client.agents_conversations_removeView.assert_called_once_with(
            channel_id="C123", view_id="T1"
        )

    def test_set_commands(self):
        self.client.agents_conversations_setCommands.return_value = {"command_count": 1}

        invoke(
            set_commands,
            self.deps,
            commands=[
                {
                    "name": "run-tests",
                    "description": "Run the tests",
                    "argument_hint": None,
                }
            ],
        )

        kwargs = self.client.agents_conversations_setCommands.call_args.kwargs
        assert kwargs["commands"] == [
            {"name": "run-tests", "description": "Run the tests"}
        ]

    def test_rename_session(self):
        invoke(rename_session, self.deps, title="Fix flaky login test")

        self.client.agents_sessions_rename.assert_called_once_with(
            channel_id="C123", title="Fix flaky login test"
        )

    def test_archive_channel_shares_the_summary(self):
        self.client.chat_postMessage.return_value = {"ts": "111.222"}

        invoke(archive_channel, self.deps, summary="Fixed it.")

        self.client.agents_conversations_archive.assert_called_once_with(
            channel_id="C123", summary_message_ts="111.222"
        )
        assert self.session.archived is True

    def test_archive_channel_closes_the_session_before_archiving(self):
        self.client.chat_postMessage.return_value = {"ts": "111.222"}

        invoke(archive_channel, self.deps, summary="Fixed it.")

        calls = [name for name, _args, _kwargs in self.client.method_calls]
        assert calls == [
            "chat_postMessage",
            "agents_sessions_setStatus",
            "agents_conversations_archive",
        ]
        self.client.agents_sessions_setStatus.assert_called_once_with(
            channel_id="C123", status="closed"
        )

    def test_archive_channel_without_origin_link_still_archives(self):
        self.client.chat_postMessage.return_value = {"ts": "111.222"}
        self.client.agents_conversations_archive.side_effect = [
            slack_error("no_origin_link"),
            {"ok": True},
        ]

        invoke(archive_channel, self.deps, summary="Fixed it.")

        assert self.client.agents_conversations_archive.call_args.kwargs == {
            "channel_id": "C123"
        }
        assert self.session.archived is True

    def test_create_code_channel_failure_leaves_the_request_in_place(self):
        self.client.agents_conversations_create.side_effect = slack_error(
            "missing_scope"
        )
        deps = RequestDeps(
            client=self.client,
            user_id="U123",
            channel_id="C_ORIGIN",
            message_ts="1.1",
            thread_ts="1.1",
        )

        assert "missing_scope" in invoke(create_code_channel, deps, title="x")
        assert deps.code_channel_id is None
        self.client.chat_postMessage.assert_not_called()

    def test_api_errors_are_returned_to_the_model(self):
        self.client.agents_sessions_rename.side_effect = slack_error("not_authorized")

        assert "not_authorized" in invoke(rename_session, self.deps, title="x")
