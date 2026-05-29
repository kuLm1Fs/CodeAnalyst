"""Tests for the terminate mechanism."""

from pathlib import Path

from agent.tools.registry import ToolResult, registry, execute_tool


class TestToolResult:
    def test_create_tool_result(self) -> None:
        result = ToolResult(content="ok", terminate=False)
        assert result.content == "ok"
        assert result.terminate is False

    def test_create_terminate_result(self) -> None:
        result = ToolResult(content="stopped", terminate=True)
        assert result.content == "stopped"
        assert result.terminate is True

    def test_from_string(self) -> None:
        result = ToolResult.from_value("hello")
        assert result.content == "hello"
        assert result.terminate is False

    def test_from_tool_result(self) -> None:
        original = ToolResult(content="test", terminate=True)
        result = ToolResult.from_value(original)
        assert result is original


class TestRegistryTerminate:
    def setup_method(self) -> None:
        """Register a test tool that can terminate."""
        self.terminate_called = False

        def terminating_tool(workspace=None):
            self.terminate_called = True
            return ToolResult(content="User rejected operation", terminate=True)

        def normal_tool(workspace=None):
            return "normal output"

        registry.register(
            name="test_terminate",
            description="Test tool that terminates",
            input_schema={"type": "object", "properties": {}},
            handler=terminating_tool,
        )
        registry.register(
            name="test_normal",
            description="Test tool that doesn't terminate",
            input_schema={"type": "object", "properties": {}},
            handler=normal_tool,
        )

    def teardown_method(self) -> None:
        """Unregister test tools."""
        registry.unregister("test_terminate")
        registry.unregister("test_normal")

    def test_execute_returns_tool_result(self, tmp_path: Path) -> None:
        result = execute_tool("test_normal", {}, workspace=tmp_path)
        assert isinstance(result, ToolResult)
        assert result.content == "normal output"
        assert result.terminate is False

    def test_execute_returns_terminate_result(self, tmp_path: Path) -> None:
        result = execute_tool("test_terminate", {}, workspace=tmp_path)
        assert isinstance(result, ToolResult)
        assert result.content == "User rejected operation"
        assert result.terminate is True

    def test_execute_unknown_tool_returns_error(self, tmp_path: Path) -> None:
        result = execute_tool("nonexistent", {}, workspace=tmp_path)
        assert isinstance(result, ToolResult)
        assert "Error" in result.content
        assert result.terminate is False

    def test_execute_handler_exception_returns_error(self, tmp_path: Path) -> None:
        def broken_tool(workspace=None):
            raise RuntimeError("boom")

        registry.register(
            name="test_broken",
            description="Broken tool",
            input_schema={"type": "object", "properties": {}},
            handler=broken_tool,
        )

        try:
            result = execute_tool("test_broken", {}, workspace=tmp_path)
            assert isinstance(result, ToolResult)
            assert "Error" in result.content
            assert result.terminate is False
        finally:
            registry.unregister("test_broken")


class TestTerminateIntegration:
    """Test terminate mechanism with agent loop."""

    def test_terminate_stops_loop(self, tmp_path: Path) -> None:
        """Verify that terminate=True stops the agent loop."""
        from types import SimpleNamespace
        from agent.runtime.loop import agent_loop

        # Register a tool that terminates
        def approval_check(workspace=None):
            return ToolResult(content="Operation denied by user", terminate=True)

        registry.register(
            name="approval_check",
            description="Check approval",
            input_schema={"type": "object", "properties": {}},
            handler=approval_check,
        )

        # Create a fake LLM client that calls the tool
        class AttrDict(dict):
            def __getattr__(self, name):
                return self[name]

        class FakeMessages:
            def __init__(self, responses):
                self.responses = responses
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return self.responses.pop(0)

        class FakeLLMClient:
            default_model = "fake-model"

            def __init__(self, responses):
                self.messages = FakeMessages(responses)

        def response(stop_reason, content):
            return SimpleNamespace(stop_reason=stop_reason, content=content)

        def tool_use_block(tool_id, name, tool_input):
            return AttrDict(type="tool_use", id=tool_id, name=name, input=tool_input)

        def text_block(text):
            return AttrDict(type="text", text=text)

        # LLM will try to call approval_check twice, but terminate should stop after first
        fake_client = FakeLLMClient([
            response("tool_use", [tool_use_block("t1", "approval_check", {})]),
            response("tool_use", [tool_use_block("t2", "approval_check", {})]),
            response("end_turn", [text_block("continued")]),
        ])

        try:
            result = agent_loop(
                messages=[{"role": "user", "content": "do something dangerous"}],
                workspace=tmp_path,
                llm_client=fake_client,
                max_steps=10,
            )

            # Should have stopped after first tool call due to terminate
            assert len(fake_client.messages.calls) == 1  # Only 1 LLM call, not 2
        finally:
            registry.unregister("approval_check")
