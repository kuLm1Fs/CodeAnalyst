from __future__ import annotations

import subprocess
from pathlib import Path


SKIPPED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}


def _workspace_root(workspace: Path | str | None = None) -> Path:
    return Path(workspace or Path.cwd()).resolve()


def _is_skipped(path: Path, workspace: Path) -> bool:
    try:
        relative = path.resolve().relative_to(workspace)
    except ValueError:
        return True
    return any(part in SKIPPED_DIRS for part in relative.parts)


def _run_rg(
    args: list[str],
    cwd: Path,
    timeout: float = 5.0,
) -> tuple[str, int]:
    try:
        result = subprocess.run(
            ["rg"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip(), result.returncode
    except FileNotFoundError:
        raise RuntimeError("rg (ripgrep) is not installed")
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"rg timed out after {timeout}s")


def _format_rg_lines(output: str, root: Path) -> list[str]:
    lines = []
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split(":", 2)
        if len(parts) >= 3:
            rel_path = parts[0]
            line_no = parts[1]
            content = parts[2].strip()
            lines.append(f"  {line_no}: {content}")
        elif len(parts) == 2:
            lines.append(f"  {parts[0]}: {parts[1].strip()}")
        else:
            lines.append(f"  {raw_line}")
    return lines


def run_file_outline(path: str, workspace: Path | str | None = None) -> str:
    try:
        root = _workspace_root(workspace)
        file_path = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()

        if not file_path.is_relative_to(root):
            return f"Error: PathError: path escapes workspace: {path}"
        if _is_skipped(file_path, root):
            return f"Error: PathError: path is ignored: {path}"
        if not file_path.exists():
            return f"Error: NotFoundError: file not found: {path}"
        if not file_path.is_file():
            return f"Error: ValidationError: path is not a file: {path}"

        output, rc = _run_rg(
            ["^\\s*(class |def |async def |import |from )", "--line-number"],
            cwd=file_path.parent,
            timeout=3.0,
        )

        if rc > 1:
            return f"Error: rg failed with exit code {rc}"

        rel_path = str(file_path.relative_to(root))
        if not output:
            return f"{rel_path}\n  (no definitions found)"

        formatted = _format_rg_lines(output, root)
        return f"{rel_path}\n" + "\n".join(formatted)

    except RuntimeError as exc:
        return f"Error: {exc}"
    except TimeoutError as exc:
        return f"Error: {exc}"
    except ValueError as exc:
        return f"Error: PathError: {exc}"
    except OSError as exc:
        return f"Error: IOError: {exc}"


def run_code_map(
    pattern: str = "**/*.py",
    workspace: Path | str | None = None,
    limit: int = 100,
) -> str:
    try:
        if limit <= 0:
            return "Error: ValidationError: limit must be greater than 0"

        root = _workspace_root(workspace)

        output, rc = _run_rg(
            ["^\\s*(class |def |async def )", "--line-number", "-g", "*.py"],
            cwd=root,
            timeout=10.0,
        )

        if rc > 1 and not output:
            return "(no Python files with definitions)"

        if rc > 1:
            return f"Error: rg failed with exit code {rc}"

        if not output:
            return "(no Python files with definitions)"

        file_groups: dict[str, list[str]] = {}
        for raw_line in output.splitlines():
            if not raw_line.strip():
                continue
            parts = raw_line.split(":", 2)
            if len(parts) < 3:
                continue
            rel_path = parts[0]
            line_no = parts[1]
            content = parts[2].strip()

            if _is_skipped(root / rel_path, root):
                continue

            if rel_path not in file_groups:
                file_groups[rel_path] = []
            file_groups[rel_path].append(f"  {line_no}: {content}")

        if not file_groups:
            return "(no Python files with definitions)"

        chunks = []
        for rel_path in sorted(file_groups.keys()):
            if len(chunks) >= limit:
                chunks.append(f"... file limit reached ({limit})")
                break
            lines = file_groups[rel_path]
            chunks.append(f"{rel_path}\n" + "\n".join(lines))

        return "\n\n".join(chunks)

    except RuntimeError as exc:
        return f"Error: {exc}"
    except TimeoutError as exc:
        return f"Error: {exc}"
    except ValueError as exc:
        return f"Error: ValidationError: {exc}"
    except OSError as exc:
        return f"Error: IOError: {exc}"


def run_symbol_lookup(
    name: str,
    workspace: Path | str | None = None,
    pattern: str = "**/*.py",
    limit: int = 50,
) -> str:
    try:
        if not isinstance(name, str) or not name.strip():
            return "Error: ValidationError: name is required"
        if limit <= 0:
            return "Error: ValidationError: limit must be greater than 0"

        root = _workspace_root(workspace)
        needle = name.strip()

        output, rc = _run_rg(
            [f"^\\s*(def |async def |class ){needle}\\b", "--line-number", "-g", "*.py"],
            cwd=root,
            timeout=5.0,
        )

        if rc > 1:
            return f"Error: rg failed with exit code {rc}"

        if not output:
            return "(no matches)"

        results = []
        for raw_line in output.splitlines():
            if not raw_line.strip():
                continue
            parts = raw_line.split(":", 2)
            if len(parts) < 3:
                continue
            rel_path = parts[0]
            line_no = parts[1]
            content = parts[2].strip()

            if _is_skipped(root / rel_path, root):
                continue

            results.append(f"{rel_path}:{line_no}: {content}")
            if len(results) >= limit:
                results.append(f"... result limit reached ({limit})")
                break

        return "\n".join(results) if results else "(no matches)"

    except RuntimeError as exc:
        return f"Error: {exc}"
    except TimeoutError as exc:
        return f"Error: {exc}"
    except ValueError as exc:
        return f"Error: ValidationError: {exc}"
    except OSError as exc:
        return f"Error: IOError: {exc}"
