"""Small, explicit Windows integration boundary (capture affinity and DPAPI)."""
import base64
import ctypes
from ctypes import wintypes
import sys


def set_capture_protection(window_id: int, enabled: bool) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Capture protection is available on Windows only."
    if sys.getwindowsversion().build < 19041:
        return False, "Capture exclusion requires Windows 10 version 2004 or Windows 11."
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
    target = 0x11 if enabled else 0
    if not user32.SetWindowDisplayAffinity(window_id, target):
        return False, f"Windows could not set capture protection (error {ctypes.get_last_error()})."
    actual = wintypes.DWORD()
    if not user32.GetWindowDisplayAffinity(window_id, ctypes.byref(actual)) or actual.value != target:
        return False, "Windows could not verify capture protection."
    return True, ("Capture exclusion requested · verify in your meeting app" if enabled
                  else "Capture protection is off")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Remembering API keys requires Windows DPAPI.")
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError("Windows could not encrypt or unlock the saved API keys.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def encrypt_keys(text: str) -> str:
    return base64.b64encode(_dpapi(text.encode("utf-8"), True)).decode("ascii")


def decrypt_keys(text: str) -> str:
    return _dpapi(base64.b64decode(text, validate=True), False).decode("utf-8")
