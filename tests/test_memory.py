from agent.memory import MemoryStore


def test_memory_store_appends_and_loads_messages(tmp_path) -> None:
    store = MemoryStore(tmp_path / ".memory")

    store.append_message("s1", {"role": "user", "content": "hello"})
    store.append_message("s1", {"role": "assistant", "content": "hi"})

    assert store.load_messages("s1") == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_memory_store_returns_empty_list_for_missing_session(tmp_path) -> None:
    store = MemoryStore(tmp_path / ".memory")

    assert store.load_messages("missing") == []


def test_memory_store_clears_session(tmp_path) -> None:
    store = MemoryStore(tmp_path / ".memory")
    store.append_message("s1", {"role": "user", "content": "hello"})

    store.clear_session("s1")

    assert store.load_messages("s1") == []


def test_memory_store_lists_sessions_with_titles_and_message_counts(tmp_path) -> None:
    store = MemoryStore(tmp_path / ".memory")
    store.append_message("s1", {"role": "user", "content": "first question"})
    store.append_message("s1", {"role": "assistant", "content": [{"type": "text", "text": "first answer"}]})
    store.append_message("s2", {"role": "assistant", "content": "hello"})

    sessions = store.list_sessions()

    assert {session["id"] for session in sessions} == {"s1", "s2"}
    session_1 = next(session for session in sessions if session["id"] == "s1")
    assert session_1["title"] == "first question"
    assert session_1["message_count"] == 2
    assert session_1["last_message"] == "first answer"
    assert session_1["updated_at"].endswith("Z")


class TestTaskMemory:
    def test_append_and_load_task_messages(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / ".memory")

        store.append_task_message("s1", "task-1", {"role": "user", "content": "explore"})
        store.append_task_message("s1", "task-1", {"role": "assistant", "content": "found X"})

        messages = store.load_task_messages("s1", "task-1")
        assert len(messages) == 2
        assert messages[0]["content"] == "explore"
        assert messages[1]["content"] == "found X"

    def test_task_messages_isolated_from_session(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / ".memory")

        store.append_message("s1", {"role": "user", "content": "main question"})
        store.append_task_message("s1", "task-1", {"role": "user", "content": "sub task"})

        session_msgs = store.load_messages("s1")
        task_msgs = store.load_task_messages("s1", "task-1")

        assert len(session_msgs) == 1
        assert session_msgs[0]["content"] == "main question"
        assert len(task_msgs) == 1
        assert task_msgs[0]["content"] == "sub task"

    def test_multiple_tasks_isolated(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / ".memory")

        store.append_task_message("s1", "task-1", {"role": "user", "content": "task 1"})
        store.append_task_message("s1", "task-2", {"role": "user", "content": "task 2"})

        assert store.load_task_messages("s1", "task-1")[0]["content"] == "task 1"
        assert store.load_task_messages("s1", "task-2")[0]["content"] == "task 2"

    def test_load_task_messages_returns_empty_for_missing(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / ".memory")
        assert store.load_task_messages("s1", "missing") == []

    def test_list_tasks(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / ".memory")

        store.append_task_message("s1", "task-1", {"role": "user", "content": "a"})
        store.append_task_message("s1", "task-2", {"role": "user", "content": "b"})
        store.append_task_message("s1", "task-2", {"role": "assistant", "content": "c"})

        tasks = store.list_tasks("s1")

        assert len(tasks) == 2
        task_ids = {t["task_id"] for t in tasks}
        assert task_ids == {"task-1", "task-2"}
        task_2 = next(t for t in tasks if t["task_id"] == "task-2")
        assert task_2["message_count"] == 2

    def test_list_tasks_empty_for_missing_session(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / ".memory")
        assert store.list_tasks("missing") == []

    def test_clear_task(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / ".memory")

        store.append_task_message("s1", "task-1", {"role": "user", "content": "a"})
        store.clear_task("s1", "task-1")

        assert store.load_task_messages("s1", "task-1") == []
