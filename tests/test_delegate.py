import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from agent.tools.delegate import run_delegate, READONLY_TOOLS
from agent.tools.registry import registry


class TestDelegateRegistration:
    def test_delegate_is_registered(self) -> None:
        assert registry.has("delegate")

    def test_delegate_schema_has_required_fields(self) -> None:
        schemas = registry.get_schemas(["delegate"])
        assert len(schemas) == 1
        schema = schemas[0]
        assert schema["name"] == "delegate"
        assert "task" in schema["input_schema"]["required"]

    def test_delegate_schema_has_optional_fields(self) -> None:
        schemas = registry.get_schemas(["delegate"])
        props = schemas[0]["input_schema"]["properties"]
        assert "tools" in props
        assert "max_steps" in props
        assert "context" in props


class TestDelegateDefaults:
    def test_readonly_tools_set(self) -> None:
        assert "read_file" in READONLY_TOOLS
        assert "glob" in READONLY_TOOLS
        assert "search_text" in READONLY_TOOLS
        assert "write_file" not in READONLY_TOOLS
        assert "safe_edit" not in READONLY_TOOLS


class TestDelegateExecution:
    @patch("agent.runtime.loop.agent_loop")
    def test_run_delegate_returns_json_result(self, mock_loop: MagicMock, tmp_path: Path) -> None:
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="found entry at main.py")]
        mock_response.stop_reason = "end_turn"
        mock_loop.return_value = mock_response

        result = run_delegate(
            task="Find the entry point",
            workspace=tmp_path,
        )

        parsed = json.loads(result)
        assert parsed["status"] == "completed"
        assert "found entry at main.py" in parsed["answer"]
        assert parsed["stop_reason"] == "end_turn"
        mock_loop.assert_called_once()

    @patch("agent.runtime.loop.agent_loop")
    def test_run_delegate_passes_task_as_user_message(self, mock_loop: MagicMock, tmp_path: Path) -> None:
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="done")]
        mock_response.stop_reason = "end_turn"
        mock_loop.return_value = mock_response

        run_delegate(task="Analyze module X", workspace=tmp_path)

        call_kwargs = mock_loop.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
        assert messages[0]["role"] == "user"
        assert "Analyze module X" in messages[0]["content"]

    @patch("agent.runtime.loop.agent_loop")
    def test_run_delegate_includes_context(self, mock_loop: MagicMock, tmp_path: Path) -> None:
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="ok")]
        mock_response.stop_reason = "end_turn"
        mock_loop.return_value = mock_response

        run_delegate(task="Check config", context="Focus on env vars", workspace=tmp_path)

        call_kwargs = mock_loop.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
        assert "Focus on env vars" in messages[0]["content"]

    @patch("agent.runtime.loop.agent_loop")
    def test_run_delegate_limits_max_steps(self, mock_loop: MagicMock, tmp_path: Path) -> None:
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="ok")]
        mock_response.stop_reason = "end_turn"
        mock_loop.return_value = mock_response

        run_delegate(task="Quick check", max_steps=3, workspace=tmp_path)

        call_kwargs = mock_loop.call_args
        max_steps = call_kwargs.kwargs.get("max_steps") or call_kwargs[1].get("max_steps")
        assert max_steps == 3

    @patch("agent.runtime.loop.agent_loop")
    def test_run_delegate_handles_exception(self, mock_loop: MagicMock, tmp_path: Path) -> None:
        mock_loop.side_effect = RuntimeError("LLM connection failed")

        result = run_delegate(task="Do something", workspace=tmp_path)

        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "LLM connection failed" in parsed["error"]

    @patch("agent.runtime.loop.agent_loop")
    def test_run_delegate_handles_list_response(self, mock_loop: MagicMock, tmp_path: Path) -> None:
        mock_loop.return_value = [{"role": "user", "content": "fallback"}]

        result = run_delegate(task="Test", workspace=tmp_path)

        parsed = json.loads(result)
        assert parsed["status"] == "completed"
        assert parsed["answer"] == ""

    @patch("agent.runtime.loop.agent_loop")
    def test_run_delegate_default_tools_are_readonly(self, mock_loop: MagicMock, tmp_path: Path) -> None:
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="ok")]
        mock_response.stop_reason = "end_turn"
        mock_loop.return_value = mock_response

        run_delegate(task="Explore codebase", workspace=tmp_path)

        assert mock_loop.called
