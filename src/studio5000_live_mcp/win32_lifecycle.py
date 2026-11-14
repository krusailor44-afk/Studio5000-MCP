"""
Win32 Lifecycle Driver for Studio 5000 Logix Designer Online Edits.

Implements the verified GUI command posting architecture from asqi-carter/lgx-mcp:
Studio 5000 is an MFC desktop application where Test Edits, Untest Edits, and Assemble Edits
are triggered via MFC WM_COMMAND messages:
- Command 32061: Test Accepted Program Edits
- Command 32062: Untest Accepted Program Edits
- Command 32063 / 32060: Assemble Accepted Program Edits
"""

import sys
import time
import ctypes
from typing import Dict, Any, Optional, Tuple

# Win32 Constants
WM_COMMAND = 0x0111
WM_NULL = 0x0000
BN_CLICKED = 0
IDOK = 1
IDCANCEL = 2
IDYES = 6
IDNO = 7
SMTO_ABORTIFHUNG = 0x0002

COMMAND_MAP = {
    "test": 32061,      # Test Accepted Program Edits
    "untest": 32062,    # Untest Accepted Program Edits
    "assemble": 32063,  # Assemble Accepted Program Edits
    "assemble_alt": 32060
}


class Win32LifecycleDriver:
    """Manages Studio 5000 MFC window interactions for online edit state transitions."""

    @staticmethod
    def is_windows() -> bool:
        return sys.platform.startswith("win")

    @classmethod
    def find_studio5000_window(cls) -> Optional[int]:
        """Finds the main window handle (HWND) of the running Studio 5000 Logix Designer instance."""
        if not cls.is_windows():
            return None

        user32 = ctypes.windll.user32
        found_hwnd = None

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def enum_windows_callback(hwnd, extra):
            nonlocal found_hwnd
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value

            # Match Logix Designer window title signatures
            if any(key in title for key in ["Logix Designer", "Studio 5000", "RSLogix 5000"]):
                found_hwnd = hwnd
                return False  # Stop enumeration
            return True

        user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)
        return found_hwnd

    @classmethod
    def get_window_title(cls, hwnd: int) -> str:
        """Retrieves title of specified HWND."""
        if not cls.is_windows() or not hwnd:
            return ""
        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value

    @classmethod
    def handle_confirmation_dialog(cls, parent_hwnd: int, timeout_seconds: float = 3.0) -> Tuple[bool, str]:
        """Waits for and automatically confirms Studio 5000 prompt dialogs (Yes / OK)."""
        if not cls.is_windows():
            return True, "Non-Windows environment"

        user32 = ctypes.windll.user32
        start_time = time.time()
        dialog_text = ""

        while time.time() - start_time < timeout_seconds:
            popup_hwnd = user32.GetLastActivePopup(parent_hwnd)
            if popup_hwnd and popup_hwnd != parent_hwnd and user32.IsWindowVisible(popup_hwnd):
                # Retrieve dialog text
                length = user32.GetWindowTextLengthW(popup_hwnd)
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(popup_hwnd, buff, length + 1)
                dialog_text = buff.value

                # Post IDYES (6) or IDOK (1) to confirm
                user32.PostMessageW(popup_hwnd, WM_COMMAND, IDYES, 0)
                user32.PostMessageW(popup_hwnd, WM_COMMAND, IDOK, 0)
                return True, dialog_text
            time.sleep(0.2)

        return False, "No confirmation dialog detected"

    @classmethod
    def execute_lifecycle_verb(cls, verb: str, timeout_seconds: float = 5.0) -> Dict[str, Any]:
        """
        Executes an online-edit lifecycle verb ('test', 'untest', 'assemble').
        Sends the specific MFC WM_COMMAND and handles the confirmation modal.
        """
        verb_norm = verb.lower().strip()
        cmd_id = COMMAND_MAP.get(verb_norm)
        if not cmd_id:
            return {
                "success": False,
                "error": f"Unknown lifecycle verb '{verb}'. Valid verbs: {list(COMMAND_MAP.keys())}"
            }

        hwnd = cls.find_studio5000_window()
        if not hwnd:
            return {
                "success": False,
                "error": "Studio 5000 window was not found. Please ensure Studio 5000 is open and online."
            }

        title = cls.get_window_title(hwnd)
        user32 = ctypes.windll.user32

        # Post WM_COMMAND to Studio 5000 main frame
        user32.PostMessageW(hwnd, WM_COMMAND, cmd_id, 0)

        # Handle modal confirmation dialog
        dialog_confirmed, dialog_text = cls.handle_confirmation_dialog(hwnd, timeout_seconds=timeout_seconds)

        return {
            "success": True,
            "verb": verb_norm,
            "command_id": cmd_id,
            "window_title": title,
            "dialog_confirmed": dialog_confirmed,
            "dialog_text": dialog_text,
            "message": f"Successfully posted {verb_norm.upper()} command ({cmd_id}) to Studio 5000 window."
        }
