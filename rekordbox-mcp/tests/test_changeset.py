"""Tests for ChangeSetManager (create, preview, apply, undo, rollback)."""

from __future__ import annotations

import pytest

from rekordbox_mcp.domain.changeset import ChangeSetManager
from rekordbox_mcp.domain.models import ChangeAction, OperationMode


class RecordingExecutor:
    """Executor that records calls and can be configured to fail on specific entity_ids."""

    def __init__(self, fail_entity_ids: set | None = None):
        self.executed: list = []
        self.reverted: list = []
        self._fail_entity_ids = fail_entity_ids or set()

    def execute(self, item) -> bool:
        if item.entity_id in self._fail_entity_ids:
            return False
        self.executed.append(item)
        return True

    def revert(self, item) -> bool:
        self.reverted.append(item)
        return True


@pytest.fixture
def executor() -> RecordingExecutor:
    return RecordingExecutor()


@pytest.fixture
def manager(executor: RecordingExecutor) -> ChangeSetManager:
    return ChangeSetManager(executor=executor, mode=OperationMode.MASTERDB)


def test_create_changeset(manager: ChangeSetManager):
    cs = manager.create_changeset("Test changeset")
    assert cs.name == "Test changeset"
    assert cs.items == []
    assert manager.get_changeset(cs.id) is cs


def test_add_change(manager: ChangeSetManager):
    cs = manager.create_changeset("Test")
    item = manager.add_change(
        cs.id,
        ChangeAction.CREATE,
        entity_type="cue",
        entity_id="cue-1",
        new_data={"position_ms": 1000},
    )
    assert item is not None
    assert item.action == ChangeAction.CREATE
    assert len(cs.items) == 1


def test_add_change_to_applied_changeset_raises(manager: ChangeSetManager):
    cs = manager.create_changeset("Test")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={})
    manager.apply(cs.id)

    with pytest.raises(ValueError):
        manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-2", new_data={})


def test_add_change_unknown_changeset_returns_none(manager: ChangeSetManager):
    result = manager.add_change("missing", ChangeAction.CREATE, "cue", "cue-1", new_data={})
    assert result is None


def test_preview(manager: ChangeSetManager):
    cs = manager.create_changeset("Preview test")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={"x": 1})

    preview = manager.preview(cs.id)
    assert preview["changeset_id"] == cs.id
    assert preview["item_count"] == 1
    assert preview["is_applied"] is False
    assert preview["changes"][0]["entity_id"] == "cue-1"


def test_preview_unknown_changeset_returns_none(manager: ChangeSetManager):
    assert manager.preview("missing") is None


def test_apply_dry_run_does_not_mark_applied(manager: ChangeSetManager, executor: RecordingExecutor):
    cs = manager.create_changeset("Dry run test")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={"x": 1})

    result = manager.apply(cs.id, dry_run=True)

    assert result["success"] is True
    assert result["dry_run"] is True
    assert cs.dry_run is True
    # Dry run still calls execute to validate
    assert len(executor.executed) == 1


def test_apply_real_marks_applied(manager: ChangeSetManager, executor: RecordingExecutor):
    cs = manager.create_changeset("Real apply")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={"x": 1})

    result = manager.apply(cs.id, dry_run=False)

    assert result["success"] is True
    assert cs.is_applied is True
    assert cs.applied_at is not None
    assert len(executor.executed) == 1


def test_apply_readonly_mode_rejects_real_apply(executor: RecordingExecutor):
    manager = ChangeSetManager(executor=executor, mode=OperationMode.READONLY)
    cs = manager.create_changeset("Readonly test")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={})

    result = manager.apply(cs.id, dry_run=False)
    assert result["success"] is False
    assert "readonly" in result["error"].lower()


def test_apply_readonly_mode_allows_dry_run(executor: RecordingExecutor):
    manager = ChangeSetManager(executor=executor, mode=OperationMode.READONLY)
    cs = manager.create_changeset("Readonly dry run")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={})

    result = manager.apply(cs.id, dry_run=True)
    assert result["success"] is True


def test_apply_already_applied_rejected(manager: ChangeSetManager):
    cs = manager.create_changeset("Already applied")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={})
    manager.apply(cs.id)

    result = manager.apply(cs.id)
    assert result["success"] is False
    assert "already applied" in result["error"].lower()


def test_apply_unknown_changeset(manager: ChangeSetManager):
    result = manager.apply("missing")
    assert result["success"] is False


def test_apply_failure_rolls_back_applied_items(executor: RecordingExecutor):
    """When one item fails, previously executed items in the same changeset should be reverted."""
    fail_executor = RecordingExecutor(fail_entity_ids={"cue-2"})
    manager = ChangeSetManager(executor=fail_executor, mode=OperationMode.MASTERDB)

    cs = manager.create_changeset("Failing changeset")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={"x": 1})
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-2", new_data={"x": 2})

    result = manager.apply(cs.id, dry_run=False)

    assert result["success"] is False
    assert cs.is_applied is False
    # cue-1 was executed then reverted because cue-2 failed
    assert len(fail_executor.executed) == 1
    assert fail_executor.executed[0].entity_id == "cue-1"
    assert len(fail_executor.reverted) == 1
    assert fail_executor.reverted[0].entity_id == "cue-1"


def test_undo_reverts_applied_changeset(manager: ChangeSetManager, executor: RecordingExecutor):
    cs = manager.create_changeset("Undo test")
    manager.add_change(
        cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={"position_ms": 1000}
    )
    manager.apply(cs.id)

    result = manager.undo(cs.id)

    assert result["success"] is True
    assert cs.is_rolled_back is True
    assert cs.rolled_back_at is not None
    # Inverse changeset should have executed a DELETE for cue-1
    inverse_items = [item for item in executor.executed if item.entity_id == "cue-1"]
    assert any(item.action == ChangeAction.DELETE for item in inverse_items)


def test_undo_not_applied_changeset_fails(manager: ChangeSetManager):
    cs = manager.create_changeset("Not applied")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={})

    result = manager.undo(cs.id)
    assert result["success"] is False
    assert "not applied" in result["error"].lower()


def test_undo_twice_fails(manager: ChangeSetManager):
    cs = manager.create_changeset("Double undo")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={})
    manager.apply(cs.id)
    manager.undo(cs.id)

    result = manager.undo(cs.id)
    assert result["success"] is False
    assert "already rolled back" in result["error"].lower()


def test_undo_readonly_mode_rejected(executor: RecordingExecutor):
    manager = ChangeSetManager(executor=executor, mode=OperationMode.MASTERDB)
    cs = manager.create_changeset("Undo readonly")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={})
    manager.apply(cs.id)

    # Switch to readonly after applying, then attempt undo
    manager._mode = OperationMode.READONLY
    result = manager.undo(cs.id)
    assert result["success"] is False
    assert "readonly" in result["error"].lower()


def test_rollback_is_alias_for_undo(manager: ChangeSetManager):
    cs = manager.create_changeset("Rollback alias")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={})
    manager.apply(cs.id)

    result = manager.rollback(cs.id)
    assert result["success"] is True
    assert cs.is_rolled_back is True


def test_delete_changeset(manager: ChangeSetManager):
    cs = manager.create_changeset("To delete")
    assert manager.delete_changeset(cs.id) is True
    assert manager.get_changeset(cs.id) is None
    assert manager.delete_changeset("missing") is False


def test_delete_applied_changeset_raises(manager: ChangeSetManager):
    cs = manager.create_changeset("Applied, can't delete")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={})
    manager.apply(cs.id)

    with pytest.raises(ValueError):
        manager.delete_changeset(cs.id)


def test_get_applied_changesets_order(manager: ChangeSetManager):
    cs1 = manager.create_changeset("First")
    manager.add_change(cs1.id, ChangeAction.CREATE, "cue", "cue-1", new_data={})
    manager.apply(cs1.id)

    cs2 = manager.create_changeset("Second")
    manager.add_change(cs2.id, ChangeAction.CREATE, "cue", "cue-2", new_data={})
    manager.apply(cs2.id)

    applied = manager.get_applied_changesets()
    assert [c.id for c in applied] == [cs1.id, cs2.id]


def test_list_changesets(manager: ChangeSetManager):
    manager.create_changeset("A")
    manager.create_changeset("B")
    assert len(manager.list_changesets()) == 2


def test_clear_history(manager: ChangeSetManager):
    cs = manager.create_changeset("To clear")
    manager.add_change(cs.id, ChangeAction.CREATE, "cue", "cue-1", new_data={})
    manager.apply(cs.id)

    manager.clear_history()
    assert manager.list_changesets() == []
    assert manager.get_applied_changesets() == []
