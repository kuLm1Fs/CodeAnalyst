from __future__ import annotations

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

BUILTIN_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read a text file from the current workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"},
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
        self._handlers: dict[str, Callable[..., str]] = {}

    def register(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[..., str],
    ) -> None:
        self._schemas[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
        }
        self._handlers[name] = handler

    def unregister(self, name: str) -> None:
        self._schemas.pop(name, None)
        self._handlers.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._handlers

    def tool_names(self) -> list[str]:
        return list(self._schemas.keys())

    def get_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        if names is None:
            return list(self._schemas.values())
        return [self._schemas[n] for n in names if n in self._schemas]

    def execute(
        self,
        name: str,
        tool_input: dict[str, Any],
        workspace: Path | str | None = None,
    ) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            return f"Error: Unknown tool: {name}"
        if not isinstance(tool_input, dict):
            return f"Error: ValidationError: tool input for {name} must be an object"

        try:
            return handler(**tool_input, workspace=workspace)
        except TypeError as e:
            return f"Error: ValidationError: invalid arguments for {name}: {e}"
        except Exception as e:
            return f"Error: tool {name} failed: {e}"


registry = ToolRegistry()

for schema in BUILTIN_SCHEMAS:
    name = schema["name"]
    handler = BUILTIN_HANDLERS.get(name)
    if handler:
        registry.register(
            name=name,
            description=schema["description"],
            input_schema=schema["input_schema"],
            handler=handler,
        )

TOOLS = registry.get_schemas()


def execute_tool(
    name: str,
    tool_input: dict[str, Any],
    workspace: Path | str | None = None,
) -> str:
    return registry.execute(name, tool_input, workspace=workspace)
