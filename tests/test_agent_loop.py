import asyncio
from pathlib import Path
from types import SimpleNamespace

from agent.memory import MemoryStore
from agent.runtime.loop import agent_loop, async_agent_loop, response_to_text


class AttrDict(dict):
    def __getattr__(self, name: str):
        return self[name]


class FakeMessages:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeLLMClient:
    default_model = "fake-model"

    def __init__(self, responses: list[object]) -> None:
        self.messages = FakeMessages(responses)


def text_block(text: str):
    return AttrDict(type="text", text=text)


def tool_use_block(tool_id: str, name: str, tool_input: dict):
    return AttrDict(type="tool_use", id=tool_id, name=name, input=tool_input)


class FakeThinkingBlock:
    type = "thinking"

    def __init__(self, thinking: str, signature: str) -> None:
        self.thinking = thinking
        self.signature = signature


def response(stop_reason: str, content: list[object]):
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def test_agent_loop_uses_injected_llm_client_for_tool_calling(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# LumaK\n", encoding="utf-8")
    fake_client = FakeLLMClient(
        [
            response(
                "tool_use",
                [tool_use_block("tool-1", "read_file", {"path": "README.md"})],
            ),
            response("end_turn", [text_block("README says LumaK.")]),
        ]
    )
    messages = [{"role": "user", "content": "Read the README"}]

    result = agent_loop(
        messages=messages,
        workspace=tmp_path,
        session_id="test-session",
        llm_client=fake_client,
    )

    assert response_to_text(result) == "README says LumaK."
    assert len(fake_client.messages.calls) == 2
    assert fake_client.messages.calls[0]["model"] == "fake-model"
    assert messages[-2] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "# LumaK",
            }
        ],
    }


def test_agent_loop_loads_and_persists_session_memory(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / ".memory")
    store.append_message("memory-session", {"role": "user", "content": "previous"})
    fake_client = FakeLLMClient(
        [response("end_turn", [text_block("done")])]
    )

    agent_loop(
        messages=[{"role": "user", "content": "current"}],
        workspace=tmp_path,
        session_id="memory-session",
        llm_client=fake_client,
        memory_store=store,
    )

    sent_messages = [
        message
        for message in fake_client.messages.calls[0]["messages"]
        if message.get("role") != "system"
    ]
    saved_messages = store.load_messages("memory-session")

    assert sent_messages[0] == {"role": "user", "content": "previous"}
    assert sent_messages[1] == {"role": "user", "content": "current"}
    assert saved_messages[0] == {"role": "user", "content": "previous"}
    assert saved_messages[1] == {"role": "user", "content": "current"}
    assert saved_messages[2] == {"role": "assistant", "content": "done"}


def test_agent_loop_does_not_persist_tool_results_to_session_memory(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# LumaK\n", encoding="utf-8")
    store = MemoryStore(tmp_path / ".memory")
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
        session_id="tool-memory-session",
        llm_client=fake_client,
        memory_store=store,
    )

    saved_messages = store.load_messages("tool-memory-session")

    assert saved_messages[0] == {"role": "user", "content": "read README"}
    assert saved_messages[1] == {"role": "assistant", "content": "read it"}
    assert len(saved_messages) == 2


def test_agent_loop_only_persists_text_not_thinking_blocks(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / ".memory")
    fake_client = FakeLLMClient(
        [
            response(
                "end_turn",
                [
                    FakeThinkingBlock("private reasoning", "signed"),
                    text_block("visible answer"),
                ],
            )
        ]
    )

    agent_loop(
        messages=[{"role": "user", "content": "think"}],
        workspace=tmp_path,
        session_id="thinking-session",
        llm_client=fake_client,
        memory_store=store,
    )

    saved_messages = store.load_messages("thinking-session")

    assert saved_messages[1] == {
        "role": "assistant",
        "content": "visible answer",
    }


def test_async_agent_loop_basic(tmp_path: Path) -> None:
    fake_client = FakeLLMClient(
        [response("end_turn", [text_block("async answer")])]
    )

    result = asyncio.run(async_agent_loop(
        messages=[{"role": "user", "content": "hello"}],
        workspace=tmp_path,
        session_id="async-test",
        llm_client=fake_client,
    ))

    assert response_to_text(result) == "async answer"


def test_async_agent_loop_with_tool_call(tmp_path: Path) -> None:
    (tmp_path / "test.txt").write_text("file content")
    fake_client = FakeLLMClient(
        [
            response(
                "tool_use",
                [tool_use_block("t1", "read_file", {"path": "test.txt"})],
            ),
            response("end_turn", [text_block("read the file")]),
        ]
    )

    result = asyncio.run(async_agent_loop(
        messages=[{"role": "user", "content": "read test.txt"}],
        workspace=tmp_path,
        session_id="async-tool-test",
        llm_client=fake_client,
    ))

    assert response_to_text(result) == "read the file"
    assert len(fake_client.messages.calls) == 2


def test_async_agent_loop_tool_filter(tmp_path: Path) -> None:
    fake_client = FakeLLMClient(
        [response("end_turn", [text_block("done")])]
    )

    result = asyncio.run(async_agent_loop(
        messages=[{"role": "user", "content": "hello"}],
        workspace=tmp_path,
        session_id="filter-test",
        llm_client=fake_client,
        tool_filter={"read_file", "glob"},
    ))

    call_tools = fake_client.messages.calls[0]["tools"]
    tool_names = {t["name"] for t in call_tools}
    assert "read_file" in tool_names
    assert "glob" in tool_names
    assert "write_file" not in tool_names


def test_agent_loop_warns_model_when_near_step_budget(tmp_path: Path) -> None:
    fake_client = FakeLLMClient(
        [response("end_turn", [text_block("done")])]
    )

    agent_loop(
        messages=[{"role": "user", "content": "review"}],
        workspace=tmp_path,
        session_id="budget-warning",
        llm_client=fake_client,
        max_steps=3,
    )

    system_message = fake_client.messages.calls[0]["messages"][0]
    assert system_message["role"] == "system"
    assert "near the tool budget" in system_message["content"]
    assert "produce the final answer" in system_message["content"]
