from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.tools.registry import ToolResult, execute_tool


@dataclass(frozen=True)
class ToolExecution:
    before_payload: dict[str, Any]
    after_payload: dict[str, Any]
    result_message: dict[str, str]
    terminate: bool = False


def tool_output_succeeded(output: str) -> bool:
    return not output.startswith("Error:")


def execute_tool_use(block: Any, *, workspace: Path | str) -> ToolExecution:
    before_payload = {
        "tool_name": block.name,
        "tool_input": block.input,
        "tool_use_id": block.id,
    }

    tool_start = time.perf_counter()
    tool_result: ToolResult | None = None
    output = ""
    success = True
    try:
        tool_result = execute_tool(block.name, block.input, workspace=workspace)
        output = tool_result.content
        success = tool_output_succeeded(output)
    except Exception as exc:
        output = str(exc)
        success = False
    finally:
        tool_elapsed = (time.perf_counter() - tool_start) * 1000

    after_payload = {
        **before_payload,
        "output": output,
        "success": success,
        "duration_ms": tool_elapsed,
        "terminate": tool_result.terminate if tool_result else False,
    }
    result_message = {
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": output,
    }

    return ToolExecution(
        before_payload=before_payload,
        after_payload=after_payload,
        result_message=result_message,
        terminate=tool_result.terminate if tool_result else False,
    )
