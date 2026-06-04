import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from agent.memory import MemoryStore
from agent.runtime.hooks import HookContext
from gateway.events import EventBroker, LiveEventHook
from gateway.app import (
    build_project_detail,
    build_project_list,
    configure_workspace,
    handle_message,
    run_chat,
    resolve_workspace_path,
    session_workspaces,
    workspace_for_session,
)
from gateway.trace_reader import read_trace_events


def test_live_event_hook_publishes_to_session_subscribers() -> None:
    async def scenario() -> dict:
        broker = EventBroker()
        queue = broker.subscribe("session-1")
        hook = LiveEventHook(broker)

        hook(
            HookContext(
                event="tool.before",
                payload={"tool_name": "read_file"},
                session_id="session-1",
                workspace="/tmp/project",
            )
        )

        event = await asyncio.wait_for(queue.get(), timeout=1)
        broker.unsubscribe("session-1", queue)
        return event

    event = asyncio.run(scenario())

    assert event == {
        "type": "agent.event",
        "event": "tool.before",
        "payload": {"tool_name": "read_file"},
        "session_id": "session-1",
        "workspace": "/tmp/project",
    }


def test_read_trace_events_loads_jsonl_for_session(tmp_path: Path) -> None:
    trace_dir = tmp_path / ".trace"
    trace_dir.mkdir()
    (trace_dir / "session-1.jsonl").write_text(
        '{"type": "session.start"}\n{"type": "session.end"}\n',
        encoding="utf-8",
    )

    events = read_trace_events(trace_dir, "session-1")

    assert events == [
        {"type": "session.start"},
        {"type": "session.end"},
    ]


def test_read_trace_events_returns_empty_list_for_missing_session(tmp_path: Path) -> None:
    assert read_trace_events(tmp_path / ".trace", "missing") == []


def test_resolve_workspace_path_rejects_missing_directory(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="workspace does not exist"):
        resolve_workspace_path(str(tmp_path / "missing"))


def test_workspace_for_session_uses_switched_workspace(tmp_path: Path) -> None:
    session_workspaces["session-test"] = tmp_path

    try:
        assert workspace_for_session("session-test") == tmp_path
    finally:
        session_workspaces.pop("session-test", None)


def test_configure_workspace_updates_default_roots(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LUMAK_WORKSPACE", raising=False)

    workspace = configure_workspace(str(tmp_path))

    assert workspace == tmp_path.resolve()
    assert workspace_for_session("new-session") == tmp_path.resolve()
    assert build_project_detail()["path"] == str(tmp_path.resolve())


def test_configure_workspace_uses_env_when_argument_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LUMAK_WORKSPACE", str(tmp_path))

    workspace = configure_workspace()

    assert workspace == tmp_path.resolve()


def test_build_project_list_returns_current_workspace(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"demo\"\n", encoding="utf-8")

    projects = build_project_list(tmp_path)

    assert projects == [
        {
            "id": "current",
            "name": "demo",
            "path": str(tmp_path),
            "active": True,
        }
    ]


def test_build_project_detail_includes_history_roots(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    project = build_project_detail(tmp_path)

    assert project["id"] == "current"
    assert project["name"] == tmp_path.name
    assert project["path"] == str(tmp_path)
    assert project["memory_root"] == str(tmp_path / ".memory")
    assert project["trace_root"] == str(tmp_path / ".trace")


def test_handle_message_serves_conversation_history(monkeypatch, tmp_path: Path) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.messages: list[dict] = []

        async def send(self, raw_message: str) -> None:
            self.messages.append(json.loads(raw_message))

    memory_root = tmp_path / ".memory"
    store = MemoryStore(memory_root)
    store.append_message("s1", {"role": "user", "content": "hello"})
    monkeypatch.setattr("gateway.app.MEMORY_ROOT", memory_root)

    websocket = FakeWebSocket()

    async def scenario() -> None:
        await handle_message(websocket, {"type": "conversation.list"})
        await handle_message(websocket, {"type": "conversation.get", "session_id": "s1"})

    asyncio.run(scenario())

    assert websocket.messages[0]["type"] == "conversation.list.response"
    assert websocket.messages[0]["conversations"][0]["id"] == "s1"
    assert websocket.messages[1] == {
        "type": "conversation.response",
        "session_id": "s1",
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_run_chat_returns_session_end_error_when_agent_returns_messages(monkeypatch, tmp_path: Path) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.messages: list[dict] = []

        async def send(self, raw_message: str) -> None:
            self.messages.append(json.loads(raw_message))

    class FakeAgent:
        def __init__(self, config) -> None:
            self.config = config

        async def async_run(self, messages: list[dict]) -> list[dict]:
            for hook in self.config.hooks:
                hook(
                    HookContext(
                        event="session.end",
                        payload={
                            "final_output": "模型调用失败：upstream 401",
                            "stop_reason": "error",
                        },
                        session_id=self.config.session_id,
                        workspace=str(self.config.workspace),
                    )
                )
            return messages

    configure_workspace(str(tmp_path))
    monkeypatch.setattr("gateway.app.Agent", FakeAgent)

    websocket = FakeWebSocket()

    asyncio.run(run_chat(websocket, {"type": "chat", "session_id": "s1", "message": "hello"}))

    responses = [message for message in websocket.messages if message["type"] == "chat.response"]
    assert responses[-1]["answer"] == "模型调用失败：upstream 401"


def test_handle_message_runs_chat_against_switched_workspace(monkeypatch, tmp_path: Path) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.messages: list[dict] = []

        async def send(self, raw_message: str) -> None:
            self.messages.append(json.loads(raw_message))

    captured = {}

    class FakeAgent:
        def __init__(self, config) -> None:
            captured["workspace"] = config.workspace
            captured["max_tokens"] = config.max_tokens
            captured["max_steps"] = config.max_steps

        async def async_run(self, messages: list[dict]) -> object:
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="switched workspace ok")],
            )

    default_workspace = tmp_path / "default"
    switched_workspace = tmp_path / "switched"
    default_workspace.mkdir()
    switched_workspace.mkdir()
    configure_workspace(str(default_workspace))
    monkeypatch.setattr("gateway.app.Agent", FakeAgent)
    websocket = FakeWebSocket()

    async def scenario() -> None:
        await handle_message(
            websocket,
            {
                "type": "project.switch",
                "session_id": "s1",
                "path": str(switched_workspace),
            },
        )
        await handle_message(
            websocket,
            {
                "type": "chat",
                "session_id": "s1",
                "message": "hello",
                "max_tokens": 2048,
                "max_steps": 7,
            },
        )

    asyncio.run(scenario())

    assert captured == {
        "workspace": switched_workspace.resolve(),
        "max_tokens": 2048,
        "max_steps": 7,
    }
    assert websocket.messages[0] == {
        "type": "project.switched",
        "session_id": "s1",
        "name": "switched",
        "path": str(switched_workspace.resolve()),
    }
    assert websocket.messages[-1] == {
        "type": "chat.response",
        "session_id": "s1",
        "answer": "switched workspace ok",
    }
