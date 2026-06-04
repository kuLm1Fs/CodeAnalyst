from pathlib import Path

from agent.tools.filesystems import (
    run_glob,
    run_read,
    run_safe_edit,
    run_search_text,
    run_write,
    safe_path,
)


def test_safe_path_rejects_parent_escape(tmp_path: Path) -> None:
    try:
        safe_path("../outside.txt", workspace=tmp_path)
    except ValueError as exc:
        assert "escapes workspace" in str(exc)
    else:
        raise AssertionError("safe_path should reject paths outside the workspace")


def test_read_rejects_ignored_directory(tmp_path: Path) -> None:
    ignored_file = tmp_path / ".git" / "config"
    ignored_file.parent.mkdir()
    ignored_file.write_text("secret", encoding="utf-8")

    result = run_read(".git/config", workspace=tmp_path)

    assert result.startswith("Error: PathError:")
    assert "ignored by workspace guard" in result


def test_read_file_supports_line_offset_and_limit(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")

    result = run_read("notes.txt", offset=2, limit=2, workspace=tmp_path)

    assert result == "three\nfour\n... (1 more lines)"


def test_glob_skips_ignored_directories(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text("print('ok')", encoding="utf-8")
    ignored_file = tmp_path / ".venv" / "lib.py"
    ignored_file.parent.mkdir()
    ignored_file.write_text("print('skip')", encoding="utf-8")

    result = run_glob("**/*.py", workspace=tmp_path)

    assert "agent.py" in result
    assert ".venv/lib.py" not in result


def test_search_text_returns_path_line_and_matching_text(tmp_path: Path) -> None:
    source = tmp_path / "agent.py"
    source.write_text("class Agent:\n    pass\n", encoding="utf-8")

    result = run_search_text("Agent", workspace=tmp_path)

    assert result == "agent.py:1: class Agent:"


def test_write_file_creates_parent_directories_inside_workspace(tmp_path: Path) -> None:
    result = run_write("docs/note.md", "hello", workspace=tmp_path)

    assert result == "Wrote 5 bytes to docs/note.md"
    assert (tmp_path / "docs" / "note.md").read_text(encoding="utf-8") == "hello"


def test_safe_edit_preview_returns_correct_diff_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("hello LumaK\n", encoding="utf-8")

    result = run_safe_edit(
        "README.md",
        old_text="hello",
        new_text="hi",
        preview=True,
        workspace=tmp_path,
    )

    assert result.startswith("Preview (no write performed):")
    assert "--- a/README.md" in result
    assert "+++ b/README.md" in result
    assert "-hello LumaK" in result
    assert "+hi LumaK" in result
    assert target.read_text(encoding="utf-8") == "hello LumaK\n"


def test_safe_edit_allows_replacing_text_with_empty_string(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("remove me\nkeep me\n", encoding="utf-8")

    result = run_safe_edit(
        "README.md",
        old_text="remove me\n",
        new_text="",
        workspace=tmp_path,
    )

    assert result.startswith("Edited README.md")
    assert target.read_text(encoding="utf-8") == "keep me\n"
