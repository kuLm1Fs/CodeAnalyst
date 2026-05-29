from pathlib import Path

from agent.tools.code_analysis import run_code_map, run_file_outline, run_symbol_lookup
from agent.tools.registry import ToolResult, execute_tool


def write_sample(path: Path) -> None:
    path.write_text(
        '''"""module docs"""

import os
from pathlib import Path


class Store:
    """store docs"""

    def append(self, item: str, retries: int = 1) -> None:
        return None


async def load(path: Path) -> str:
    return str(path)
''',
        encoding="utf-8",
    )


def test_file_outline_returns_definitions(tmp_path: Path) -> None:
    write_sample(tmp_path / "sample.py")

    output = run_file_outline("sample.py", workspace=tmp_path)

    assert "sample.py" in output
    assert "import os" in output
    assert "from pathlib import Path" in output
    assert "class Store" in output
    assert "def append" in output
    assert "async def load" in output


def test_file_outline_returns_error_for_missing_file(tmp_path: Path) -> None:
    output = run_file_outline("missing.py", workspace=tmp_path)

    assert "Error" in output
    assert "not found" in output


def test_file_outline_returns_error_for_non_python_file(tmp_path: Path) -> None:
    (tmp_path / "test.txt").write_text("hello")

    output = run_file_outline("test.txt", workspace=tmp_path)

    assert "no definitions found" in output


def test_code_map_returns_project_structure(tmp_path: Path) -> None:
    write_sample(tmp_path / "sample.py")

    output = run_code_map(workspace=tmp_path)

    assert "sample.py" in output
    assert "class Store" in output
    assert "def append" in output
    assert "async def load" in output


def test_code_map_returns_message_for_empty_project(tmp_path: Path) -> None:
    output = run_code_map(workspace=tmp_path)

    assert "no Python files" in output


def test_symbol_lookup_finds_definitions(tmp_path: Path) -> None:
    write_sample(tmp_path / "sample.py")

    output = run_symbol_lookup("append", workspace=tmp_path)

    assert "sample.py" in output
    assert "def append" in output


def test_symbol_lookup_returns_no_matches_for_missing(tmp_path: Path) -> None:
    write_sample(tmp_path / "sample.py")

    output = run_symbol_lookup("nonexistent", workspace=tmp_path)

    assert "no matches" in output


def test_registry_exposes_code_analysis_tools(tmp_path: Path) -> None:
    write_sample(tmp_path / "sample.py")

    result = execute_tool("file_outline", {"path": "sample.py"}, workspace=tmp_path)

    assert isinstance(result, ToolResult)
    assert "sample.py" in result.content
    assert "class Store" in result.content
