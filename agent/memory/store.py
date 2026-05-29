from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

class MemoryStore:
    def __init__(self, root: Path | str = ".memory") -> None:
        self.root = Path(root)
        self.session_dir = self.root / "sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def session_path(self, session_id: str) -> Path:
        return self.session_dir / f"{session_id}.jsonl"

    def _task_dir(self, session_id: str) -> Path:
        task_dir = self.session_dir / session_id / "tasks"
        task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir

    def _task_path(self, session_id: str, task_id: str) -> Path:
        return self._task_dir(session_id) / f"{task_id}.jsonl"

    def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        with self.session_path(session_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message, ensure_ascii=False) + "\n")

    def load_messages(self, session_id: str) -> list[dict[str, Any]]:
        path = self.session_path(session_id)
        if not path.exists():
            return []

        messages = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                messages.append(json.loads(line))
        return messages

    def append_task_message(
        self, session_id: str, task_id: str, message: dict[str, Any]
    ) -> None:
        path = self._task_path(session_id, task_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message, ensure_ascii=False) + "\n")

    def load_task_messages(
        self, session_id: str, task_id: str
    ) -> list[dict[str, Any]]:
        path = self._task_path(session_id, task_id)
        if not path.exists():
            return []

        messages = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                messages.append(json.loads(line))
        return messages

    def list_tasks(self, session_id: str) -> list[dict[str, Any]]:
        task_dir = self._task_dir(session_id)
        tasks: list[dict[str, Any]] = []

        for path in sorted(task_dir.glob("*.jsonl")):
            messages = self._load_path(path)
            updated_at = datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat().replace("+00:00", "Z")
            tasks.append({
                "task_id": path.stem,
                "message_count": len(messages),
                "updated_at": updated_at,
            })

        return tasks

    def clear_session(self, session_id: str) -> None:
        self.session_path(session_id).unlink(missing_ok=True)

    def clear_task(self, session_id: str, task_id: str) -> None:
        self._task_path(session_id, task_id).unlink(missing_ok=True)

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []

        for path in self.session_dir.glob("*.jsonl"):
            messages = self._load_path(path)
            updated_at = datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat().replace("+00:00", "Z")
            sessions.append(
                {
                    "id": path.stem,
                    "title": self._title_for_messages(messages),
                    "updated_at": updated_at,
                    "message_count": len(messages),
                    "last_message": self._preview_for_message(messages[-1]) if messages else "",
                }
            )

        return sorted(sessions, key=lambda item: str(item["updated_at"]), reverse=True)

    def _load_path(self, path: Path) -> list[dict[str, Any]]:
        messages = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                messages.append(json.loads(line))
        return messages

    def _title_for_messages(self, messages: list[dict[str, Any]]) -> str:
        for message in messages:
            if message.get("role") == "user":
                preview = self._preview_for_message(message)
                if preview:
                    return preview[:28]
        return "新对话"

    def _preview_for_message(self, message: dict[str, Any]) -> str:
        content = message.get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts = [
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            result = " ".join(part for part in text_parts if part).strip()
            return result if result else "(工具调用)"
        return "(工具调用)"
