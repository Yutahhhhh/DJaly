"""Reveal a filesystem item without shell expansion of its name."""
import ctypes
import os


def reveal_windows_file(path: str) -> None:
    # FastAPI runs this synchronous operation on a worker thread. Initialize
    # COM on that thread and use a PIDL so %, &, Unicode and UNC names survive.
    ole = ctypes.OleDLL("ole32")
    shell = ctypes.OleDLL("shell32")
    ole.CoInitialize.argtypes = [ctypes.c_void_p]
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    shell.SHParseDisplayName.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_ulong, ctypes.c_void_p]
    shell.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_ulong]
    ole.CoInitialize(None)
    item = ctypes.c_void_p()
    try:
        shell.SHParseDisplayName(os.path.abspath(path), None, ctypes.byref(item), 0, None)
        shell.SHOpenFolderAndSelectItems(item, 0, None, 0)
    finally:
        if item.value:
            ole.CoTaskMemFree(item)
        ole.CoUninitialize()
