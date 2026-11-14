"""
State Management and Adapter Routing for Studio 5000 MCP Server.

Routes tool calls dynamically based on whether the active project is an offline
.L5X file or a live .ACD project connected via the Logix Designer SDK.
"""

import os
import logging
from typing import Optional, Dict, Any

from .base import PLCAdapter, AdapterMode, PLCAdapterError
from .logix_online import LogixOnlineAdapter
from .logix_offline import LogixOfflineAdapter
from ..sdk_client import SDK_AVAILABLE

logger = logging.getLogger("studio5000_live_mcp.adapters.router")


class AdapterRouter:
    """
    Manages active project lifecycle and routes MCP tool requests to either
    the LogixOnlineAdapter or LogixOfflineAdapter.
    """

    def __init__(self, initial_project_path: Optional[str] = None):
        self._online_adapter = LogixOnlineAdapter()
        self._offline_adapter = LogixOfflineAdapter()
        self._active_mode: AdapterMode = AdapterMode.UNCONFIGURED
        self._active_path: Optional[str] = None

        # Check environment variables
        env_path = initial_project_path or os.environ.get("STUDIO5000_ACD_PATH") or os.environ.get("STUDIO5000_L5X_PATH")
        if env_path and os.path.exists(env_path):
            self.set_active_project(env_path)

    @property
    def mode(self) -> AdapterMode:
        return self._active_mode

    @property
    def active_project_path(self) -> Optional[str]:
        return self._active_path

    @property
    def online_adapter(self) -> LogixOnlineAdapter:
        return self._online_adapter

    @property
    def offline_adapter(self) -> LogixOfflineAdapter:
        return self._offline_adapter

    def set_active_project(self, project_path: str) -> Dict[str, Any]:
        """
        Switches the active project context between live .ACD and offline .L5X.
        Automatically instantiates and configures the corresponding adapter.
        """
        abs_path = os.path.abspath(project_path)
        if not os.path.exists(abs_path):
            raise PLCAdapterError(
                f"Project file not found: {abs_path}",
                remediation="Verify the file path exists on disk and is accessible."
            )

        ext = os.path.splitext(abs_path)[1].lower()
        if ext == ".acd":
            self._online_adapter.set_project(abs_path)
            self._active_mode = AdapterMode.ONLINE
            self._active_path = abs_path
            os.environ["STUDIO5000_ACD_PATH"] = abs_path
            logger.info(f"Switched to ONLINE mode with ACD: {abs_path}")
            return {
                "status": "success",
                "mode": self._active_mode.value,
                "project_path": abs_path,
                "file_type": "ACD (Studio 5000 Project)",
                "sdk_available": SDK_AVAILABLE,
                "message": "Configured for live online controller interaction via Logix SDK."
            }
        elif ext in (".l5x", ".xml"):
            self._offline_adapter.set_project(abs_path)
            self._active_mode = AdapterMode.OFFLINE
            self._active_path = abs_path
            os.environ["STUDIO5000_L5X_PATH"] = abs_path
            logger.info(f"Switched to OFFLINE mode with L5X: {abs_path}")
            return {
                "status": "success",
                "mode": self._active_mode.value,
                "project_path": abs_path,
                "file_type": "L5X (Rockwell Logix XML)",
                "message": "Configured for offline code generation, XML parsing, and NeutralText translation."
            }
        else:
            raise PLCAdapterError(
                f"Unsupported file format '{ext}'. Expected .ACD or .L5X.",
                remediation="Provide an .ACD file for live online edits or an .L5X file for offline engineering."
            )

    def get_adapter(self) -> PLCAdapter:
        """Returns the appropriate adapter for the current project mode."""
        if self._active_mode == AdapterMode.ONLINE:
            return self._online_adapter
        elif self._active_mode == AdapterMode.OFFLINE:
            return self._offline_adapter
        else:
            # Fallback to offline adapter for general code gen and parsing tasks
            return self._offline_adapter

    def get_status(self) -> Dict[str, Any]:
        """Returns the current state and capabilities of the MCP server."""
        return {
            "mode": self._active_mode.value,
            "active_project_path": self._active_path,
            "sdk_available": SDK_AVAILABLE,
            "online_ready": self._online_adapter.is_connected,
            "offline_ready": self._offline_adapter.is_connected,
            "supported_tools": {
                "online": ["read_routine", "read_tag", "propose_edit", "test_edits", "untest_edits", "assemble_edits"],
                "offline": ["parse_l5x", "translate_to_neutral_text", "generate_l5x_import", "validate_l5x_file"],
                "universal": ["set_active_project", "get_project_status"]
            }
        }
