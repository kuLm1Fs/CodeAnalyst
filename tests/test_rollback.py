from pathlib import Path

from agent.runtime.rollback import SessionRollback


class TestSessionRollback:
    def test_snapshot_and_rollback(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        rollback = SessionRollback(tmp_path)
        rollback.snapshot("write_file", {"path": "test.txt"})

        test_file.write_text("modified")
        assert test_file.read_text() == "modified"

        restored = rollback.rollback()
        assert test_file.read_text() == "original"
        assert len(restored) == 1

    def test_snapshot_new_file(self, tmp_path: Path) -> None:
        test_file = tmp_path / "new.txt"

        rollback = SessionRollback(tmp_path)
        rollback.snapshot("write_file", {"path": "new.txt"})

        test_file.write_text("created")
        assert test_file.exists()

        rollback.rollback()
        assert not test_file.exists()

    def test_commit_clears_snapshots(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        rollback = SessionRollback(tmp_path)
        rollback.snapshot("write_file", {"path": "test.txt"})

        rollback.commit()
        assert not rollback.has_changes

    def test_snapshot_ignores_non_write_tools(self, tmp_path: Path) -> None:
        rollback = SessionRollback(tmp_path)
        rollback.snapshot("read_file", {"path": "test.txt"})
        rollback.snapshot("glob", {"pattern": "*.txt"})

        assert not rollback.has_changes

    def test_snapshot_ignores_preview(self, tmp_path: Path) -> None:
        rollback = SessionRollback(tmp_path)
        rollback.snapshot("safe_edit", {"path": "test.txt", "preview": True})

        assert not rollback.has_changes

    def test_snapshot_only_once_per_file(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("v1")

        rollback = SessionRollback(tmp_path)
        rollback.snapshot("write_file", {"path": "test.txt"})

        test_file.write_text("v2")
        rollback.snapshot("write_file", {"path": "test.txt"})

        rollback.rollback()
        assert test_file.read_text() == "v1"


class TestRollbackScoping:
    def test_create_sub_scope(self, tmp_path: Path) -> None:
        parent = SessionRollback(tmp_path, scope="session")
        child = parent.create_sub_scope("task-1")

        assert child.scope == "session:task-1"
        assert child.parent is parent

    def test_sub_scope_rollback_independent(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        parent = SessionRollback(tmp_path)
        child = parent.create_sub_scope("task-1")

        child.snapshot("write_file", {"path": "test.txt"})
        test_file.write_text("child-modified")

        child.rollback()
        assert test_file.read_text() == "original"
        assert not parent.has_changes

    def test_sub_scope_commit_to_parent(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        parent = SessionRollback(tmp_path)
        child = parent.create_sub_scope("task-1")

        child.snapshot("write_file", {"path": "test.txt"})
        child.commit()

        assert parent.has_changes
        assert not child.has_changes

    def test_nested_scopes(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        root = SessionRollback(tmp_path, scope="session")
        mid = root.create_sub_scope("task-1")
        leaf = mid.create_sub_scope("sub-1")

        leaf.snapshot("write_file", {"path": "test.txt"})
        test_file.write_text("leaf-modified")

        leaf.rollback()
        assert test_file.read_text() == "original"
        assert not mid.has_changes
        assert not root.has_changes

    def test_commit_chain_to_root(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        root = SessionRollback(tmp_path, scope="session")
        mid = root.create_sub_scope("task-1")
        leaf = mid.create_sub_scope("sub-1")

        leaf.snapshot("write_file", {"path": "test.txt"})
        leaf.commit()
        mid.commit()

        assert root.has_changes
        assert not mid.has_changes
        assert not leaf.has_changes
