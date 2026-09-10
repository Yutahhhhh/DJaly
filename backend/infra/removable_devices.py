"""Discover external volumes and request the OS's safe-removal operation."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import os
import platform
import plistlib
import re
import struct
import subprocess
import time


def _windows_api():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetLogicalDrives.restype = wintypes.DWORD
    api.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    api.GetDriveTypeW.restype = wintypes.UINT
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    api.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR, wintypes.DWORD]
    api.GetVolumeNameForVolumeMountPointW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    api.GetDiskFreeSpaceExW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_ulonglong),
        ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong)]
    return api


def _windows_volume_id(api, root):
    name = ctypes.create_unicode_buffer(1024)
    return name.value if api.GetVolumeNameForVolumeMountPointW(root, name, len(name)) else None


def _windows_bus_type(api, root):
    # Query-only access works for ordinary users and never locks/dismounts a disk.
    handle = api.CreateFileW("\\\\.\\" + root[:2], 0, 3, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        return None
    try:
        query = ctypes.create_string_buffer(struct.pack("<II", 0, 0) + b"\0" * 4)
        descriptor = ctypes.create_string_buffer(4096)
        returned = wintypes.DWORD()
        if api.DeviceIoControl(handle, 0x2D1400, query, len(query), descriptor,
                               len(descriptor), ctypes.byref(returned), None) and returned.value >= 36:
            return struct.unpack_from("<I", descriptor.raw, 28)[0]
        return None
    finally:
        api.CloseHandle(handle)


def _windows_devices():
    api = _windows_api()
    mask = api.GetLogicalDrives()
    rows = []
    for number in range(26):
        if not mask & (1 << number):
            continue
        root = chr(65 + number) + ":\\"
        kind = api.GetDriveTypeW(root)
        # USB SSD/HDDs report DRIVE_FIXED, unlike removable flash media.
        if kind != 2 and not (kind == 3 and _windows_bus_type(api, root) == 7):
            continue
        label = ctypes.create_unicode_buffer(261)
        filesystem = ctypes.create_unicode_buffer(261)
        serial, maximum, flags = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
        if not api.GetVolumeInformationW(root, label, len(label), ctypes.byref(serial),
                ctypes.byref(maximum), ctypes.byref(flags), filesystem, len(filesystem)):
            continue  # Empty removable-media slots are not connected volumes.
        volume = _windows_volume_id(api, root)
        if not volume:
            continue
        available, capacity, free = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
        if not api.GetDiskFreeSpaceExW(root, ctypes.byref(available), ctypes.byref(capacity), ctypes.byref(free)):
            continue
        rows.append({"id": volume, "device_identifier": root[:2], "volume_uuid": volume,
            "label": label.value or root[:2], "mount_path": root, "filesystem": filesystem.value,
            "capacity_bytes": capacity.value, "free_bytes": available.value,
            "read_only": bool(flags.value & 0x80000), "connected": True})
    return rows


def devices():
    if platform.system() == "Windows":
        return _windows_devices()
    if platform.system() != "Darwin":
        return []
    rows = []
    for mount in sorted(Path("/Volumes").iterdir() if Path("/Volumes").is_dir() else []):
        try:
            result = subprocess.run(["/usr/sbin/diskutil", "info", "-plist", str(mount)],
                                    check=True, capture_output=True, timeout=5)
            info = plistlib.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
            continue
        if info.get("Internal") or not info.get("MountPoint"):
            continue
        persistent = str(info.get("VolumeUUID") or info.get("DiskUUID") or info.get("DeviceIdentifier"))
        rows.append({"id": persistent, "device_identifier": info.get("DeviceIdentifier"),
            "volume_uuid": info.get("VolumeUUID"), "label": info.get("VolumeName") or mount.name,
            "mount_path": info.get("MountPoint"), "filesystem": info.get("FilesystemType"),
            "capacity_bytes": info.get("TotalSize"), "free_bytes": info.get("FreeSpace"),
            "read_only": not bool(info.get("Writable", False)), "connected": True})
    return rows


def eject(current):
    if platform.system() != "Windows":
        result = subprocess.run(["/usr/sbin/diskutil", "eject", current["mount_path"]],
                                check=True, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()
    root = current["mount_path"]
    if not re.fullmatch(r"[A-Z]:\\", root):
        raise ValueError("Windowsのドライブパスが不正です")
    api = _windows_api()
    if _windows_volume_id(api, root) != current["volume_uuid"]:
        raise ValueError("USBの接続状態が変わりました。再読み込みしてください")
    shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = "$ErrorActionPreference='Stop'; $item=(New-Object -ComObject Shell.Application).Namespace(17).ParseName($env:PLUMDECK_EJECT_ROOT); if (!$item) { throw 'Volume not found' }; $item.InvokeVerb('Eject')"
    subprocess.run([str(shell), "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "PLUMDECK_EJECT_ROOT": root}, capture_output=True, check=True,
        timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    # Shell removal is asynchronous. Do not mark a still-mounted/in-use volume
    # as ejected, and never force a dismount or discard pending writes.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _windows_volume_id(api, root) != current["volume_uuid"]:
            return "WindowsでUSBを安全に取り外しました"
        time.sleep(.25)
    raise ValueError("USBを取り外せませんでした。使用中のファイルやrekordboxを閉じて再試行してください")
