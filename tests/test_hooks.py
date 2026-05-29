import asyncio
from pathlib import Path
from types import SimpleNamespace

from agent.runtime.agent.agent import Agent, AgentConfig
from agent.runtime.hooks import HookManager, SubAgentEventBus, SubAgentEvent
from agent.runtime.loop import agent_loop
from agent.trace.trace import AgentTrace, TraceHook


class AttrDict(dict):
    def __getattr__(self, name: str):
        return self[name]


class FakeMessages:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses

    def create(self, **kwargs):
        return self.responses.pop(0)


class FakeLLMClient:
    default_model = "fake-model"

    def __init__(self, responses: list[object]) -> None:
        self.messages = FakeMessages(responses)


def text_block(text: str):
    return AttrDict(type="text", text=text)


def tool_use_block(tool_id: str, name: str, tool_input: dict):
    return AttrDict(type="tool_use", id=tool_id, name=name, input=tool_input)


def response(stop_reason: str, content: list[object]):
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def test_hook_manager_registers_and_emits_context(tmp_path: Path) -> None:
    events = []
    manager = HookManager()

    manager.register(lambda context: events.append(context))
    manager.emit(
        "custom.event",
        {"ok": True},
        session_id="session-1",
        workspace=str(tmp_path),
    )

    assert events[0].event == "custom.event"
    assert events[0].payload == {"ok": True}
    assert events[0].session_id == "session-1"
    assert events[0].workspace == str(tmp_path)


def test_trace_hook_records_emitted_context(tmp_path: Path) -> None:
    trace = AgentTrace(
        workspace=tmp_path,
        session_id="trace-hook-session",
        trace_dir=tmp_path / ".trace",
    )
    trace_hook = TraceHook(trace, payload_limit=20)
    manager = HookManager([trace_hook])

    manager.emit(
        "custom.event",
        {"ok": True, "output": "x" * 40},
        session_id="trace-hook-session",
        workspace=str(tmp_path),
    )

    trace_text = trace.trace_path.read_text(encoding="utf-8")

    assert '"type": "custom.event"' in trace_text
    assert '"ok": true' in trace_text
    assert '"length": 40' in trace_text
    assert '"truncated": true' in trace_text


def test_agent_loop_does_not_write_trace_by_default(tmp_path: Path) -> None:
    fake_client = FakeLLMClient(
        [response("end_turn", [text_block("done")])]
    )
    trace_path = Path(".trace") / "trace-disabled-session.jsonl"
    trace_path.unlink(missing_ok=True)

    agent_loop(
        messages=[{"role": "user", "content": "hello"}],
        workspace=tmp_path,
        session_id="trace-disabled-session",
        llm_client=fake_client,
    )

    assert not trace_path.exists()


def test_agent_loop_trace_records_session_start_once_when_enabled(tmp_path: Path) -> None:
    fake_client = FakeLLMClient(
        [response("end_turn", [text_block("done")])]
    )
    trace_path = Path(".trace") / "single-session-start.jsonl"
    trace_path.unlink(missing_ok=True)

    agent_loop(
        messages=[{"role": "user", "content": "hello"}],
        workspace=tmp_path,
        session_id="single-session-start",
        llm_client=fake_client,
        trace_enabled=True,
    )

    trace_text = trace_path.read_text(encoding="utf-8")

    assert trace_text.count('"type": "session.start"') == 1


def test_agent_loop_emits_lifecycle_hooks(tmp_path: Path) -> None:
    events = []
    fake_client = FakeLLMClient(
        [response("end_turn", [text_block("done")])]
    )

    agent_loop(
        messages=[{"role": "user", "content": "hello"}],
        workspace=tmp_path,
        session_id="hook-session",
        llm_client=fake_client,
        hooks=[lambda context: events.append((context.event, context.payload))],
    )

    event_names = [event for event, _ in events]

    assert event_names == [
        "session.start",
        "skills.selected",
        "message",
        "loop.iteration.start",
        "model.request",
        "model.response",
        "loop.model.duration",
        "session.end",
    ]
    assert events[4][1]["model"] == "fake-model"
    assert events[4][1]["message_count"] == 1
    assert events[-1][1]["final_output"] == "done"


def test_agent_loop_emits_tool_hooks(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# LumaK\n", encoding="utf-8")
    events = []
    fake_client = FakeLLMClient(
        [
            response(
                "tool_use",
                [tool_use_block("tool-1", "read_file", {"path": "README.md"})],
            ),
            response("end_turn", [text_block("read it")]),
        ]
    )

    agent_loop(
        messages=[{"role": "user", "content": "read README"}],
        workspace=tmp_path,
        session_id="hook-tool-session",
        llm_client=fake_client,
        hooks=[lambda context: events.append((context.event, context.payload))],
    )

    tool_before = [payload for event, payload in events if event == "tool.before"]
    tool_after = [payload for event, payload in events if event == "tool.after"]

    assert tool_before[0] == {
        "tool_name": "read_file",
        "tool_input": {"path": "README.md"},
        "tool_use_id": "tool-1",
    }
    assert tool_after[0]["tool_name"] == "read_file"
    assert tool_after[0]["success"] is True
    assert "# LumaK" in tool_after[0]["output"]
    assert isinstance(tool_after[0]["duration_ms"], float)


def test_agent_config_passes_hooks_to_loop(tmp_path: Path) -> None:
    events = []
    fake_client = FakeLLMClient(
        [response("end_turn", [text_block("done")])]
    )
    agent = Agent(
        AgentConfig(
            workspace=tmp_path,
            session_id="agent-hook-session",
            llm_client=fake_client,
            hooks=[lambda context: events.append(context.event)],
        )
    )

    agent.run([{"role": "user", "content": "hello"}])

    assert "session.start" in events
    assert "session.end" in events


class TestAsyncHooks:
    def test_sync_hook_still_works(self, tmp_path: Path) -> None:
        events = []
        manager = HookManager()

        def sync_hook(context):
            events.append(context.event)

        manager.register(sync_hook)
        manager.emit("test", {}, session_id="s1", workspace=str(tmp_path))

        assert events == ["test"]

    def test_async_hook_with_emit_async(self, tmp_path: Path) -> None:
        events = []
        manager = HookManager()

        async def async_hook(context):
            events.append(context.event)

        manager.register(async_hook)

        asyncio.run(manager.emit_async("test", {}, session_id="s1", workspace=str(tmp_path)))

        assert events == ["test"]

    def test_mixed_sync_async_hooks(self, tmp_path: Path) -> None:
        events = []
        manager = HookManager()

        def sync_hook(context):
            events.append(f"sync:{context.event}")

        async def async_hook(context):
            events.append(f"async:{context.event}")

        manager.register(sync_hook)
        manager.register(async_hook)

        asyncio.run(manager.emit_async("test", {}, session_id="s1", workspace=str(tmp_path)))

        assert "sync:test" in events
        assert "async:test" in events


class TestSubAgentEventBus:
    def test_subscribe_and_emit(self) -> None:
        bus = SubAgentEventBus()
        queue = bus.subscribe("task-1")

        event = SubAgentEvent(task_id="task-1", event_type="started", payload={})
        bus.emit_sync(event)

        assert not queue.empty()
        received = queue.get_nowait()
        assert received.event_type == "started"

    def test_isolated_per_task(self) -> None:
        bus = SubAgentEventBus()
        queue1 = bus.subscribe("task-1")
        queue2 = bus.subscribe("task-2")

        event1 = SubAgentEvent(task_id="task-1", event_type="started", payload={})
        event2 = SubAgentEvent(task_id="task-2", event_type="completed", payload={})
        bus.emit_sync(event1)
        bus.emit_sync(event2)

        assert queue1.get_nowait().event_type == "started"
        assert queue2.get_nowait().event_type == "completed"

    def test_unsubscribe(self) -> None:
        bus = SubAgentEventBus()
        queue = bus.subscribe("task-1")
        bus.unsubscribe("task-1", queue)

        event = SubAgentEvent(task_id="task-1", event_type="started", payload={})
        bus.emit_sync(event)

        assert queue.empty()

    def test_async_emit(self) -> None:
        bus = SubAgentEventBus()
        queue = bus.subscribe("task-1")

        event = SubAgentEvent(task_id="task-1", event_type="started", payload={})

        async def collect():
            await bus.emit(event)
            return await queue.get()

        received = asyncio.run(collect())
        assert received.event_type == "started"
