import os
import sys

import pytest

from infra import removable_devices


def test_windows_keeps_usb_fixed_disks_and_excludes_internal_disks(monkeypatch):
    class Api:
        def GetLogicalDrives(self):
            return (1 << 2) | (1 << 4) | (1 << 5)

        def GetDriveTypeW(self, root):
            return 2 if root == "F:\\" else 3

        def GetVolumeInformationW(self, root, label, size, serial, maximum, flags, filesystem, fs_size):
            label.value = "音楽 USB"
            filesystem.value = "exFAT"
            flags._obj.value = 0x80000 if root == "F:\\" else 0
            return 1

        def GetDiskFreeSpaceExW(self, root, available, capacity, free):
            available._obj.value = 100
            capacity._obj.value = 200
            free._obj.value = 100
            return 1

    monkeypatch.setattr(removable_devices, "_windows_api", Api)
    monkeypatch.setattr(removable_devices, "_windows_bus_type", lambda api, root: 7 if root == "E:\\" else 11)
    monkeypatch.setattr(removable_devices, "_windows_volume_id", lambda api, root: "volume-" + root[0])
    rows = removable_devices._windows_devices()
    assert [row["mount_path"] for row in rows] == ["E:\\", "F:\\"]
    assert [row["read_only"] for row in rows] == [False, True]
    assert rows[0]["label"] == "音楽 USB"


@pytest.mark.skipif(sys.platform != "win32", reason="Exercises the native Windows volume APIs")
def test_native_windows_volume_discovery_does_not_select_system_disk():
    rows = removable_devices._windows_devices()
    for row in rows:
        assert row["device_identifier"].upper() != os.environ["SystemDrive"].upper()
        assert row["id"] == row["volume_uuid"]
        assert row["capacity_bytes"] >= row["free_bytes"] >= 0


def test_eject_rejects_reused_drive_letter_before_asking_windows(monkeypatch):
    monkeypatch.setattr(removable_devices.platform, "system", lambda: "Windows")
    monkeypatch.setattr(removable_devices, "_windows_api", lambda: object())
    monkeypatch.setattr(removable_devices, "_windows_volume_id", lambda api, root: "replacement")
    with pytest.raises(ValueError, match="接続状態が変わりました"):
        removable_devices.eject({"mount_path": "E:\\", "volume_uuid": "original"})
