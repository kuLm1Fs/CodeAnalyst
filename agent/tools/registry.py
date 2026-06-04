from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent.tools.filesystems import (
    run_edit,
    run_glob,
    run_read,
    run_search_text,
    run_safe_edit,
    run_write,
)
from agent.tools.code_analysis import (
    run_code_map,
    run_file_outline,
    run_symbol_lookup,
)


@dataclass
class ToolResult:
    """Structured tool result with optional terminate signal."""
    content: str
    terminate: bool = False

    @classmethod
    def from_value(cls, value: str | ToolResult) -> ToolResult:
        """Wrap a string or pass through a ToolResult."""
        if isinstance(value, cls):
            return value
        return cls(content=str(value))

BUILTIN_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read UTF-8 text lines from a file in the current workspace. Use offset and limit to page through large files by line number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "limit": {"type": "integer", "description": "Maximum number of lines to read."},
                "offset": {"type": "integer", "description": "Zero-based line offset to start reading from."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write text content to a file in the current workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "glob",
        "description": "Find files matching a glob pattern in the current workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "search_text",
        "description": "Search text in files under the current workspace and return path, line number, and matching line.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "pattern": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "safe_edit",
        "description": "Safely edit a file by replacing exact text once, with optional diff preview.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "preview": {"type": "boolean"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "file_outline",
        "description": "Return a Python AST outline for one file, including imports, classes, functions, methods, signatures, and line ranges.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "code_map",
        "description": "Return a Python AST code map for files in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "symbol_lookup",
        "description": "Find Python class, function, or method definitions by exact symbol name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "pattern": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["name"],
        },
    },
]

BUILTIN_HANDLERS: dict[str, Callable[..., str]] = {
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "glob": run_glob,
    "search_text": run_search_text,
    "safe_edit": run_safe_edit,
    "file_outline": run_file_outline,
    "code_map": run_code_map,
    "symbol_lookup": run_symbol_lookup,
}


class ToolRegistry:
    def __init__(self) -> None:
        self._schemas: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, Callable[..., str | ToolResult]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[..., str | ToolResult],
        *,
        permission: str = "workspace.read",
        writes_files: bool = False,
        timeout_seconds: float = 30.0,
        retry_count: int = 1,
    ) -> None:
        self._schemas[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
        }
        self._handlers[name] = handler
        self._metadata[name] = {
            "permission": permission,
            "writes_files": writes_files,
            "timeout_seconds": timeout_seconds,
            "retry_count": retry_count,
        }

    def unregister(self, name: str) -> None:
        self._schemas.pop(name, None)
        self._handlers.pop(name, None)
        self._metadata.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._handlers

    def tool_names(self) -> list[str]:
        return list(self._schemas.keys())

    def get_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        if names is None:
            return list(self._schemas.values())
        return [self._schemas[n] for n in names if n in self._schemas]

    def get_mcp_like_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        schemas = self.get_schemas(names)
        exported = []
        for schema in schemas:
            name = schema["name"]
            metadata = self._metadata[name]
            attempts = int(metadata["retry_count"]) + 1
            exported.append(
                {
                    "name": name,
                    "description": schema["description"],
                    "parameters": schema["input_schema"],
                    "permission": metadata["permission"],
                    "writes_files": metadata["writes_files"],
                    "timeout_policy": {
                        "timeout_seconds": metadata["timeout_seconds"],
                        "retry_count": metadata["retry_count"],
                        "fallback_message": f"Error: ToolExecutionFailed: {name} failed after {attempts} attempt(s).",
                    },
                }
            )
        return exported

    def _run_handler_with_timeout(
        self,
        handler: Callable[..., str | ToolResult],
        timeout_seconds: float,
        **kwargs: Any,
    ) -> str | ToolResult:
        results: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                results.put(("result", handler(**kwargs)))
            except Exception as exc:
                results.put(("error", exc))

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(timeout=timeout_seconds)
        if thread.is_alive():
            raise TimeoutError

        kind, value = results.get_nowait()
        if kind == "error":
            raise value
        return value

    def execute(
        self,
        name: str,
        tool_input: dict[str, Any],
        workspace: Path | str | None = None,
    ) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(content=f"Error: Unknown tool: {name}")
        if not isinstance(tool_input, dict):
            return ToolResult(content=f"Error: ValidationError: tool input for {name} must be an object")

        metadata = self._metadata[name]
        retry_count = int(metadata["retry_count"])
        timeout_seconds = float(metadata["timeout_seconds"])

        for attempt in range(retry_count + 1):
            try:
                result = self._run_handler_with_timeout(
                    handler,
                    timeout_seconds,
                    **tool_input,
                    workspace=workspace,
                )
                return ToolResult.from_value(result)
            except TypeError as e:
                return ToolResult(content=f"Error: ValidationError: invalid arguments for {name}: {e}")
            except TimeoutError:
                if attempt >= retry_count:
                    return ToolResult(
                        content=f"Error: ToolTimeout: {name} exceeded {timeout_seconds:g}s; returning fallback result."
                    )
            except Exception as e:
                if attempt >= retry_count:
                    return ToolResult(content=f"Error: tool {name} failed: {e}")

        return ToolResult(content=f"Error: ToolExecutionFailed: {name} failed after {retry_count + 1} attempt(s).")


registry = ToolRegistry()

for schema in BUILTIN_SCHEMAS:
    name = schema["name"]
    handler = BUILTIN_HANDLERS.get(name)
    if handler:
        writes_files = name in {"write_file", "safe_edit"}
        registry.register(
            name=name,
            description=schema["description"],
            input_schema=schema["input_schema"],
            handler=handler,
            permission="workspace.write" if writes_files else "workspace.read",
            writes_files=writes_files,
        )

def _delegate_handler(**kwargs: Any) -> str:
    from agent.tools.delegate import run_delegate
    return run_delegate(**kwargs)


registry.register(
    name="delegate",
    description=(
        "Delegate a sub-task to a specialized sub-agent. "
        "The sub-agent runs in the same workspace with a subset of tools. "
        "Returns a JSON result with the sub-agent's answer."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task description for the sub-agent",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names the sub-agent can use. Default: all read-only tools",
            },
            "max_steps": {
                "type": "integer",
                "description": "Max steps for the sub-agent. Default: 6",
            },
            "context": {
                "type": "string",
                "description": "Additional context to pass to the sub-agent",
            },
            "role": {
                "type": "string",
                "enum": ["explorer", "editor", "reviewer"],
                "description": "Role of the sub-agent. Default: explorer",
            },
        },
        "required": ["task"],
    },
    handler=_delegate_handler,
    permission="workspace.delegate",
    writes_files=True,
    timeout_seconds=120.0,
)

TOOLS = registry.get_schemas()


def execute_tool(
    name: str,
    tool_input: dict[str, Any],
    workspace: Path | str | None = None,
) -> ToolResult:
    return registry.execute(name, tool_input, workspace=workspace)
