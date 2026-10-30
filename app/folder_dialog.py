"""The Windows "choose a folder" dialog (the same Explorer-style one other apps use).

A web page is not allowed to read a local folder path, so the app asks Windows itself. This calls the
shell's IFileOpenDialog directly through ctypes, which needs nothing installed - the bundled Python
has no tkinter, and the old Tk dialog looked out of place anyway.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import POINTER, byref, c_void_p, c_wchar_p, wintypes
from pathlib import Path

# IDs from the Windows SDK (shobjidl_core.h).
_CLSID_FILE_OPEN_DIALOG = "{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}"
_IID_IFILE_OPEN_DIALOG = "{D57C7288-D4AD-4768-BE02-9D969532D960}"
_IID_ISHELL_ITEM = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"

_FOS_PICKFOLDERS = 0x00000020
_FOS_FORCEFILESYSTEM = 0x00000040
_FOS_PATHMUSTEXIST = 0x00000800
_SIGDN_FILESYSPATH = 0x80058000
_CLSCTX_INPROC_SERVER = 0x1
_COINIT_APARTMENTTHREADED = 0x2
_HRESULT_CANCELLED = 0x800704C7  # ERROR_CANCELLED as an HRESULT

# Positions of the methods we call in each COM interface's function table.
_RELEASE = 2
_SHOW = 3
_SET_OPTIONS, _GET_OPTIONS, _SET_FOLDER, _SET_TITLE, _GET_RESULT = 9, 10, 12, 17, 20
_GET_DISPLAY_NAME = 5


class _GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "_GUID":
        guid = cls()
        ole32 = ctypes.windll.ole32
        ole32.CLSIDFromString.argtypes = [c_wchar_p, POINTER(_GUID)]
        if ole32.CLSIDFromString(text, byref(guid)) != 0:
            raise OSError(f"bad GUID {text}")
        return guid


def _method(obj: c_void_p, index: int, *argtypes):
    """The COM method at `index` of `obj`'s function table, callable as method(obj, *args)."""
    table = ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0], POINTER(c_void_p))
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(table[index])


def _release(obj: c_void_p) -> None:
    if obj:
        ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)(
            ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0], POINTER(c_void_p))[_RELEASE]
        )(obj)


def choose_folder(title: str, initial: str | None = None) -> str | None:
    """Shows the dialog and returns the chosen folder, or None if the person cancelled.
    Blocks until the dialog closes. Must not be called from two threads at once."""
    if sys.platform != "win32":
        raise OSError("The folder dialog is only available on Windows")

    ole32, shell32 = ctypes.windll.ole32, ctypes.windll.shell32
    ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)  # fine if this thread already did
    dialog, start, result = c_void_p(), c_void_p(), c_void_p()
    try:
        ole32.CoCreateInstance.argtypes = [POINTER(_GUID), c_void_p, wintypes.DWORD, POINTER(_GUID), POINTER(c_void_p)]
        ole32.CoCreateInstance.restype = ctypes.HRESULT
        ole32.CoCreateInstance(
            byref(_GUID.parse(_CLSID_FILE_OPEN_DIALOG)), None, _CLSCTX_INPROC_SERVER,
            byref(_GUID.parse(_IID_IFILE_OPEN_DIALOG)), byref(dialog),
        )

        options = wintypes.DWORD()
        _method(dialog, _GET_OPTIONS, POINTER(wintypes.DWORD))(dialog, byref(options))
        _method(dialog, _SET_OPTIONS, wintypes.DWORD)(
            dialog, options.value | _FOS_PICKFOLDERS | _FOS_FORCEFILESYSTEM | _FOS_PATHMUSTEXIST
        )
        _method(dialog, _SET_TITLE, c_wchar_p)(dialog, title)

        if initial and Path(initial).is_dir():
            shell32.SHCreateItemFromParsingName.argtypes = [c_wchar_p, c_void_p, POINTER(_GUID), POINTER(c_void_p)]
            shell32.SHCreateItemFromParsingName.restype = ctypes.HRESULT
            try:
                shell32.SHCreateItemFromParsingName(str(Path(initial)), None, byref(_GUID.parse(_IID_ISHELL_ITEM)), byref(start))
                _method(dialog, _SET_FOLDER, c_void_p)(dialog, start)
            except OSError:
                pass  # start wherever Windows likes

        try:
            # Owned by the window the person just clicked in (the app's), so it opens in front of it
            # rather than behind it, as a dialog from a background process otherwise can.
            ctypes.windll.user32.GetForegroundWindow.restype = wintypes.HWND  # 64-bit handle
            owner = ctypes.windll.user32.GetForegroundWindow()
            _method(dialog, _SHOW, wintypes.HWND)(dialog, owner)
        except OSError as exc:
            if (getattr(exc, "winerror", None) or 0) & 0xFFFFFFFF == _HRESULT_CANCELLED:
                return None
            raise

        _method(dialog, _GET_RESULT, POINTER(c_void_p))(dialog, byref(result))
        name = c_wchar_p()
        _method(result, _GET_DISPLAY_NAME, wintypes.DWORD, POINTER(c_wchar_p))(result, _SIGDN_FILESYSPATH, byref(name))
        try:
            return name.value
        finally:
            ole32.CoTaskMemFree(name)
    finally:
        _release(result)
        _release(start)
        _release(dialog)
        ole32.CoUninitialize()
