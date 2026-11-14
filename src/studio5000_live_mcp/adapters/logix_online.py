"""
Logix Online Adapter for Studio 5000 Live MCP Server.

Interacts directly with physical or emulated Rockwell Logix controllers via:
1. Rockwell Logix Designer Python SDK (logix_designer_sdk) for live tag reads,
   routine partial exports, and online edit zone acceptance.
2. Win32 MFC Automation for lifecycle state transitions (test, untest, assemble).
3. Industrial Safety Gates enforcing strict tag and routine access boundaries.
"""

import os
import logging
from typing import Dict, List, Optional, Any

from .base import PLCAdapter, AdapterMode, UnsupportedOperationError, PLCAdapterError
from ..sdk_client import Studio5000SDKClient, SDK_AVAILABLE
from ..win32_lifecycle import Win32LifecycleDriver
from ..safety_validator import SafetyValidator, SafetyGateViolation
from ..l5x_builder import L5XBuilder, L5XValidationError

logger = logging.getLogger("studio5000_live_mcp.adapters.online")


class LogixOnlineAdapter(PLCAdapter):
    """
    Adapter implementing live online PLC interactions using the official
    Rockwell Logix Designer SDK and Studio 5000 GUI lifecycle driver.
    """

    def __init__(self, acd_path: Optional[str] = None):
        self._acd_path: Optional[str] = os.path.abspath(acd_path) if acd_path else None
        self._client: Optional[Studio5000SDKClient] = None
        if self._acd_path and os.path.exists(self._acd_path):
            self._client = Studio5000SDKClient(self._acd_path)

    @property
    def adapter_mode(self) -> AdapterMode:
        return AdapterMode.ONLINE

    @property
    def active_project_path(self) -> Optional[str]:
        return self._acd_path

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def set_project(self, acd_path: str) -> None:
        """Sets or switches the active .ACD project file."""
        abs_path = os.path.abspath(acd_path)
        if not os.path.exists(abs_path):
            raise PLCAdapterError(
                f"ACD project file does not exist: {abs_path}",
                remediation="Provide a valid absolute path to an existing Studio 5000 .ACD project."
            )
        self._acd_path = abs_path
        self._client = Studio5000SDKClient(self._acd_path)
        logger.info(f"LogixOnlineAdapter configured with ACD: {self._acd_path}")

    def _ensure_client(self) -> Studio5000SDKClient:
        if not self._client:
            if not self._acd_path:
                raise PLCAdapterError(
                    "No .ACD project configured for online adapter. Set STUDIO5000_ACD_PATH or call set_active_project.",
                    remediation="Call set_active_project with the path to your .ACD file."
                )
            self._client = Studio5000SDKClient(self._acd_path)
        return self._client

    # ==========================================
    # READ OPERATIONS
    # ==========================================

    def read_routine(self, program_name: str, routine_name: str) -> Dict[str, Any]:
        """Fetches live ladder logic from controller with pending edit states."""
        client = self._ensure_client()
        try:
            return client.read_routine(program_name, routine_name)
        except Exception as e:
            logger.error(f"Failed to read online routine '{program_name}/{routine_name}': {e}", exc_info=True)
            raise PLCAdapterError(
                f"Failed to read online routine '{program_name}/{routine_name}': {e}",
                remediation="Ensure Studio 5000 is open with the controller online and routine name is spelled correctly."
            )

    def read_tag(self, tag_name: str, program_name: Optional[str] = None) -> Dict[str, Any]:
        """Fetches live tag value, data type, and access properties from controller."""
        client = self._ensure_client()
        try:
            return client.read_tag(tag_name, program_name)
        except Exception as e:
            logger.error(f"Failed to read online tag '{tag_name}': {e}", exc_info=True)
            raise PLCAdapterError(
                f"Failed to read online tag '{tag_name}': {e}",
                remediation="Verify tag exists in controller or program scope and controller is in online or run mode."
            )

    # ==========================================
    # ONLINE EDIT LIFECYCLE
    # ==========================================

    def propose_edit(
        self,
        program_name: str,
        routine_name: str,
        insert_position: int,
        replace_count: int,
        new_rungs: List[str],
        new_rung_comments: Optional[List[str]] = None,
        new_tags: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Pushes staged ladder logic changes to controller as pending edits (AcceptEdits)."""
        client = self._ensure_client()

        # 1. Modernize legacy comparison mnemonics and pre-validate RLL ladder syntax
        modernized_rungs = [L5XBuilder.modernize_rll_mnemonics(r) for r in new_rungs]
        for idx, rung in enumerate(modernized_rungs):
            L5XBuilder.validate_rll_syntax(rung, rung_idx=insert_position + idx)

        # 2. SDK execution with built-in safety gate checks
        try:
            return client.propose_edit(
                program_name=program_name,
                routine_name=routine_name,
                insert_position=insert_position,
                replace_count=replace_count,
                new_rungs=modernized_rungs,
                new_rung_comments=new_rung_comments,
                new_tags=new_tags
            )
        except SafetyGateViolation:
            raise
        except Exception as e:
            logger.error(f"propose_edit failed for '{program_name}/{routine_name}': {e}", exc_info=True)
            raise PLCAdapterError(
                f"propose_edit failed on live controller: {e}",
                remediation="Verify controller is online, keyswitch is in REM (Remote Run/Prog), and logic contains no syntax errors."
            )

    def test_edits(self, program_name: str, routine_name: str) -> Dict[str, Any]:
        """Activates Test Mode for pending edits via Studio 5000 MFC verb 32061."""
        self._ensure_client()
        logger.info(f"Issuing test_edits for '{program_name}/{routine_name}'")
        gui_res = Win32LifecycleDriver.execute_lifecycle_verb("test")
        return {
            "status": "tested" if gui_res.get("success") else "test_post_failed",
            "program": program_name,
            "routine": routine_name,
            "zone_state": "tested",
            "controller_running_edits": True,
            "driver_result": gui_res,
            "message": (
                f"Test mode command issued for '{program_name}/{routine_name}'. "
                "The controller is now executing the proposed logic while preserving the original. "
                "Verify machine operation carefully. Call 'untest_edits' to revert, or 'assemble_edits' to finalize."
            )
        }

    def untest_edits(self, program_name: str, routine_name: str) -> Dict[str, Any]:
        """Reverts controller back to original logic via Studio 5000 MFC verb 32062."""
        self._ensure_client()
        logger.info(f"Issuing untest_edits for '{program_name}/{routine_name}'")
        gui_res = Win32LifecycleDriver.execute_lifecycle_verb("untest")
        return {
            "status": "untested" if gui_res.get("success") else "untest_post_failed",
            "program": program_name,
            "routine": routine_name,
            "zone_state": "untested",
            "controller_running_edits": False,
            "driver_result": gui_res,
            "message": (
                f"Untest command issued for '{program_name}/{routine_name}'. "
                "The controller has reverted to scanning the original logic."
            )
        }

    def assemble_edits(self, program_name: str, routine_name: str, confirmed: bool = False) -> Dict[str, Any]:
        """
        Permanently commits pending edits via Studio 5000 MFC verb 32063.
        MANDATORY SAFEGUARD: Requires confirmed=True.
        """
        self._ensure_client()
        if not confirmed:
            return {
                "status": "REJECTED_BY_SAFEGUARD",
                "error": (
                    "HUMAN-IN-THE-LOOP SAFEGUARD TRIGGERED: Assembling edits permanently overwrites "
                    "original controller logic in non-volatile memory. You must review tested behavior with the "
                    "lead controls engineer and explicitly pass confirmed=True to finalize."
                ),
                "confirmed": False
            }

        logger.info(f"Assembling edits for '{program_name}/{routine_name}' with explicit confirmation.")
        gui_res = Win32LifecycleDriver.execute_lifecycle_verb("assemble")
        return {
            "status": "assembled" if gui_res.get("success") else "assemble_post_failed",
            "program": program_name,
            "routine": routine_name,
            "zone_state": "none",
            "driver_result": gui_res,
            "message": (
                f"Edits in '{program_name}/{routine_name}' have been assembled and finalized. "
                "Original logic has been replaced with the new logic permanently."
            )
        }

    # ==========================================
    # OFFLINE / CODE GEN UTILITIES
    # ==========================================

    def parse_l5x(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """Delegates L5X parsing to offline utility."""
        from .logix_offline import LogixOfflineAdapter
        return LogixOfflineAdapter().parse_l5x(file_path)

    def translate_to_neutral_text(self, xml_content_or_file: str) -> Dict[str, Any]:
        """Delegates NeutralText translation to offline utility."""
        from .logix_offline import LogixOfflineAdapter
        return LogixOfflineAdapter().translate_to_neutral_text(xml_content_or_file)

    def generate_l5x_import(
        self,
        target_type: str,
        target_name: str,
        rungs: List[str],
        program_name: Optional[str] = None,
        controller_name: str = "Controller",
        description: str = "",
        rung_comments: Optional[List[str]] = None,
        parameters: Optional[List[Dict[str, Any]]] = None,
        local_tags: Optional[List[Dict[str, Any]]] = None,
        software_revision: str = "38.00",
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Delegates L5X generation to offline utility."""
        from .logix_offline import LogixOfflineAdapter
        return LogixOfflineAdapter().generate_l5x_import(
            target_type=target_type,
            target_name=target_name,
            rungs=rungs,
            program_name=program_name,
            controller_name=controller_name,
            description=description,
            rung_comments=rung_comments,
            parameters=parameters,
            local_tags=local_tags,
            software_revision=software_revision,
            output_path=output_path
        )
