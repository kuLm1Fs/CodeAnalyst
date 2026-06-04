from pathlib import Path
from typing import Any
import time

from agent.tools.registry import (
    ToolRegistry,
    ToolResult,
    execute_tool,
    registry,
    TOOLS,
)


def test_execute_tool_rejects_unknown_tool(tmp_path: Path) -> None:
    result = execute_tool("missing_tool", {}, workspace=tmp_path)

    assert isinstance(result, ToolResult)
    assert result.content == "Error: Unknown tool: missing_tool"
    assert result.terminate is False


def test_execute_tool_rejects_non_object_input(tmp_path: Path) -> None:
    result = execute_tool("read_file", "README.md", workspace=tmp_path)  # type: ignore[arg-type]

    assert isinstance(result, ToolResult)
    assert result.content == "Error: ValidationError: tool input for read_file must be an object"


def test_execute_tool_reports_invalid_arguments(tmp_path: Path) -> None:
    result = execute_tool("read_file", {"unexpected": "value"}, workspace=tmp_path)

    assert isinstance(result, ToolResult)
    assert result.content.startswith("Error: ValidationError: invalid arguments for read_file:")


class TestToolRegistry:
    def test_register_and_has(self) -> None:
        reg = ToolRegistry()
        assert not reg.has("my_tool")

        reg.register(
            name="my_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {}},
            handler=lambda workspace=None: "ok",
        )
        assert reg.has("my_tool")

    def test_unregister(self) -> None:
        reg = ToolRegistry()
        reg.register(
            name="temp",
            description="temp tool",
            input_schema={"type": "object", "properties": {}},
            handler=lambda workspace=None: "ok",
        )
        assert reg.has("temp")

        reg.unregister("temp")
        assert not reg.has("temp")

    def test_unregister_missing_is_noop(self) -> None:
        reg = ToolRegistry()
        reg.unregister("nonexistent")

    def test_tool_names(self) -> None:
        reg = ToolRegistry()
        reg.register(
            name="a",
            description="a",
            input_schema={"type": "object", "properties": {}},
            handler=lambda workspace=None: "a",
        )
        reg.register(
            name="b",
            description="b",
            input_schema={"type": "object", "properties": {}},
            handler=lambda workspace=None: "b",
        )
        assert reg.tool_names() == ["a", "b"]

    def test_get_schemas_all(self) -> None:
        reg = ToolRegistry()
        reg.register(
            name="x",
            description="x tool",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
            handler=lambda workspace=None: "x",
        )
        schemas = reg.get_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "x"
        assert schemas[0]["description"] == "x tool"
        assert "q" in schemas[0]["input_schema"]["properties"]

    def test_get_schemas_filtered(self) -> None:
        reg = ToolRegistry()
        reg.register(
            name="a",
            description="a",
            input_schema={"type": "object", "properties": {}},
            handler=lambda workspace=None: "a",
        )
        reg.register(
            name="b",
            description="b",
            input_schema={"type": "object", "properties": {}},
            handler=lambda workspace=None: "b",
        )
        schemas = reg.get_schemas(["a"])
        assert len(schemas) == 1
        assert schemas[0]["name"] == "a"

    def test_get_schemas_filtered_skips_missing(self) -> None:
        reg = ToolRegistry()
        reg.register(
            name="a",
            description="a",
            input_schema={"type": "object", "properties": {}},
            handler=lambda workspace=None: "a",
        )
        schemas = reg.get_schemas(["a", "nonexistent"])
        assert len(schemas) == 1

    def test_execute_success(self, tmp_path: Path) -> None:
        reg = ToolRegistry()

        def echo(text: str, workspace: Any = None) -> str:
            return text

        reg.register(
            name="echo",
            description="echo",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            handler=echo,
        )
        result = reg.execute("echo", {"text": "hello"}, workspace=tmp_path)
        assert isinstance(result, ToolResult)
        assert result.content == "hello"
        assert result.terminate is False

    def test_execute_unknown_tool(self, tmp_path: Path) -> None:
        reg = ToolRegistry()
        result = reg.execute("nope", {}, workspace=tmp_path)
        assert isinstance(result, ToolResult)
        assert result.content == "Error: Unknown tool: nope"

    def test_execute_non_dict_input(self, tmp_path: Path) -> None:
        reg = ToolRegistry()
        reg.register(
            name="t",
            description="t",
            input_schema={"type": "object", "properties": {}},
            handler=lambda workspace=None: "ok",
        )
        result = reg.execute("t", "bad", workspace=tmp_path)  # type: ignore[arg-type]
        assert isinstance(result, ToolResult)
        assert "ValidationError" in result.content

    def test_execute_handler_exception(self, tmp_path: Path) -> None:
        reg = ToolRegistry()

        def broken(workspace: Any = None) -> str:
            raise RuntimeError("boom")

        reg.register(
            name="broken",
            description="broken",
            input_schema={"type": "object", "properties": {}},
            handler=broken,
        )
        result = reg.execute("broken", {}, workspace=tmp_path)
        assert isinstance(result, ToolResult)
        assert "Error: tool broken failed: boom" in result.content

    def test_execute_retries_transient_failures(self, tmp_path: Path) -> None:
        reg = ToolRegistry()
        attempts = 0

        def flaky(workspace: Any = None) -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary")
            return "ok"

        reg.register(
            name="flaky",
            description="flaky",
            input_schema={"type": "object", "properties": {}},
            handler=flaky,
            retry_count=1,
        )

        result = reg.execute("flaky", {}, workspace=tmp_path)

        assert result.content == "ok"
        assert attempts == 2

    def test_execute_times_out_with_fallback_message(self, tmp_path: Path) -> None:
        reg = ToolRegistry()

        def slow(workspace: Any = None) -> str:
            time.sleep(0.2)
            return "late"

        reg.register(
            name="slow",
            description="slow",
            input_schema={"type": "object", "properties": {}},
            handler=slow,
            timeout_seconds=0.01,
        )

        result = reg.execute("slow", {}, workspace=tmp_path)

        assert result.content == "Error: ToolTimeout: slow exceeded 0.01s; returning fallback result."

    def test_export_mcp_like_schemas_includes_policy_and_permissions(self) -> None:
        reg = ToolRegistry()
        reg.register(
            name="write_note",
            description="write note",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            handler=lambda workspace=None: "ok",
            permission="workspace.write",
            writes_files=True,
            timeout_seconds=3.0,
            retry_count=2,
        )

        schemas = reg.get_mcp_like_schemas()

        assert schemas == [
            {
                "name": "write_note",
                "description": "write note",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                "permission": "workspace.write",
                "writes_files": True,
                "timeout_policy": {
                    "timeout_seconds": 3.0,
                    "retry_count": 2,
                    "fallback_message": "Error: ToolExecutionFailed: write_note failed after 3 attempt(s).",
                },
            }
        ]


class TestBackwardCompatibility:
    def test_tools_is_list_of_schemas(self) -> None:
        assert isinstance(TOOLS, list)
        assert len(TOOLS) > 0
        for tool in TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_global_registry_has_builtins(self) -> None:
        assert registry.has("read_file")
        assert registry.has("write_file")
        assert registry.has("glob")
        assert registry.has("search_text")
        assert registry.has("safe_edit")
        assert registry.has("file_outline")
        assert registry.has("code_map")
        assert registry.has("symbol_lookup")

    def test_read_file_schema_documents_line_pagination(self) -> None:
        read_schema = next(schema for schema in TOOLS if schema["name"] == "read_file")

        properties = read_schema["input_schema"]["properties"]
        assert "offset" in properties
        assert "line" in read_schema["description"].lower()
        assert "line" in properties["limit"]["description"].lower()
        assert "line" in properties["offset"]["description"].lower()

    def test_execute_tool_wrapper_works(self, tmp_path: Path) -> None:
        (tmp_path / "test.txt").write_text("hello")
        result = execute_tool("read_file", {"path": "test.txt"}, workspace=tmp_path)
        assert isinstance(result, ToolResult)
        assert "hello" in result.content

    def test_tools_matches_registry_schemas(self) -> None:
        reg_schemas = registry.get_schemas()
        assert len(TOOLS) == len(reg_schemas)
        for tool, schema in zip(TOOLS, reg_schemas):
            assert tool["name"] == schema["name"]
