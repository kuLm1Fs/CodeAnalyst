from pathlib import Path
import tomllib


def test_python_package_includes_all_tui_runtime_js_files() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))

    data_files = pyproject["tool"]["setuptools"]["data-files"]["share/lumak/tui/dist"]
    packaged = {Path(path).name for path in data_files}
    runtime_js = {path.name for path in (repo_root / "tui" / "dist").glob("*.js")}

    assert runtime_js <= packaged


def test_python_package_includes_tui_package_json_for_module_type() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))

    data_files = pyproject["tool"]["setuptools"]["data-files"]

    assert "tui/package.json" in data_files["share/lumak/tui"]
