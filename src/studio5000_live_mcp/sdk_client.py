"""
Rockwell Logix Designer SDK Client.

Wraps the official Rockwell Logix Designer Python SDK (logix_designer_sdk) to interact
directly with active .ACD projects while online with the controller.
"""

import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# Try importing the official Rockwell Logix Designer SDK
try:
    import logix_designer_sdk as sdk
    from logix_designer_sdk.enums import (
        ConnectedState,
        OperationMode,
        PartialImportOption,
        DataType
    )
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False
    sdk = None

from .l5x_builder import L5XBuilder
from .safety_validator import SafetyValidator, SafetyGateViolation


class Studio5000SDKClient:
    """Manages active online connection and SDK operations with Studio 5000 Logix Designer."""

    def __init__(self, acd_path: Optional[str] = None):
        self.acd_path = acd_path
        self.project: Optional[Any] = None
        self.is_online = False
        self.controller_name: str = "UnknownController"
        self.software_revision: str = "38.00"

    def connect(self, acd_path: Optional[str] = None) -> Dict[str, Any]:
        """Opens the .ACD project and goes online with the PLC."""
        if acd_path:
            self.acd_path = acd_path

        if not self.acd_path:
            raise ValueError("No .ACD project path specified.")

        path_obj = Path(self.acd_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Project file not found: {self.acd_path}")

        if not SDK_AVAILABLE:
            raise RuntimeError(
                "Rockwell Logix Designer SDK (logix_designer_sdk) is not installed. "
                "Install the wheel from your Studio 5000 SDK directory."
            )

        # Open project via SDK
        self.project = sdk.LogixProject.open_logix_project(str(path_obj))

        # Check and transition to online mode
        state = self.project.read_connected_state()
        if state != ConnectedState.ONLINE:
            self.project.go_online()

        self.is_online = (self.project.read_connected_state() == ConnectedState.ONLINE)

        # Retrieve controller metadata from export
        self._cache_controller_info()

        return {
            "status": "connected",
            "project_file": str(path_obj),
            "is_online": self.is_online,
            "controller_name": self.controller_name,
            "software_revision": self.software_revision
        }

    def _cache_controller_info(self) -> None:
        """Reads controller name and software revision from project root."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tf:
                temp_path = tf.name

            # Export controller root context
            self.project.partial_export_to_xml_file("Controller", temp_path)
            tree = ET.parse(temp_path)
            root = tree.getroot()

            self.software_revision = root.attrib.get("SoftwareRevision", "38.00")
            controller_elem = root.find("Controller")
            if controller_elem is not None:
                self.controller_name = controller_elem.attrib.get("Name", "LogixController")
        except Exception:
            pass
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def read_routine(self, program_name: str, routine_name: str) -> Dict[str, Any]:
        """
        Exports and reads the ladder logic of a specified routine.
        Returns parsed rungs with their rung numbers, pending state, comments, and logic text.
        """
        if not self.project:
            self.connect()

        xpath = f"Controller/Programs/Program[@Name='{program_name}']/Routines/Routine[@Name='{routine_name}']"

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tf:
            temp_path = tf.name

        try:
            self.project.partial_export_to_xml_file(xpath, temp_path)
            tree = ET.parse(temp_path)
            root = tree.getroot()

            routine_elem = root.find(f".//Routine[@Name='{routine_name}']")
            if routine_elem is None:
                raise ValueError(f"Routine '{routine_name}' not found in program '{program_name}'.")

            routine_type = routine_elem.attrib.get("Type", "RLL")

            rungs_data = []
            has_pending_edits = False

            rll_elem = routine_elem.find("RLLContent")
            if rll_elem is not None:
                for rung in rll_elem.findall("Rung"):
                    rung_num = int(rung.attrib.get("Number", 0))
                    rung_type = rung.attrib.get("Type", "N")  # N=Normal, I=Insert pending, R=Replace pending, D=Delete pending
                    if rung_type != "N":
                        has_pending_edits = True

                    comment_elem = rung.find("Comment")
                    comment = comment_elem.text if (comment_elem is not None and comment_elem.text) else ""

                    text_elem = rung.find("Text")
                    logic_text = text_elem.text if (text_elem is not None and text_elem.text) else ""

                    rungs_data.append({
                        "number": rung_num,
                        "type": rung_type,
                        "comment": comment.strip(),
                        "logic": logic_text.strip()
                    })

            return {
                "program": program_name,
                "routine": routine_name,
                "type": routine_type,
                "rung_count": len(rungs_data),
                "has_pending_edits": has_pending_edits,
                "rungs": rungs_data
            }
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def read_tag(self, tag_name: str, program_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Reads live tag value and data type from the controller online.
        """
        if not self.project:
            self.connect()

        # Build fully qualified tag path
        tag_path = f"Program:{program_name}.{tag_name}" if program_name else tag_name

        # Query metadata via export
        meta_xpath = (
            f"Controller/Programs/Program[@Name='{program_name}']/Tags/Tag[@Name='{tag_name}']"
            if program_name else
            f"Controller/Tags/Tag[@Name='{tag_name}']"
        )

        metadata: Dict[str, Any] = {}
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tf:
            temp_path = tf.name

        try:
            self.project.partial_export_to_xml_file(meta_xpath, temp_path)
            tree = ET.parse(temp_path)
            tag_elem = tree.getroot().find(".//Tag")
            if tag_elem is not None:
                metadata = tag_elem.attrib
        except Exception:
            pass
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # Read live value via SDK typed helpers
        live_val: Any = None
        data_type = metadata.get("DataType", "UNKNOWN")

        try:
            if data_type.upper() == "BOOL":
                live_val = self.project.get_tag_value_bool(tag_path, OperationMode.ONLINE)
            elif data_type.upper() in ("DINT", "INT", "SINT", "LINT"):
                live_val = self.project.get_tag_value_dint(tag_path, OperationMode.ONLINE)
            elif data_type.upper() in ("REAL", "LREAL"):
                live_val = self.project.get_tag_value_real(tag_path, OperationMode.ONLINE)
            elif data_type.upper() == "STRING":
                live_val = self.project.get_tag_value_string(tag_path, OperationMode.ONLINE)
            else:
                raw_bytes = self.project.get_tag_value(tag_path, OperationMode.ONLINE, DataType.RAW)
                live_val = f"<bytes len={len(raw_bytes)}>"
        except Exception as e:
            live_val = f"<Read Error: {e}>"

        return {
            "tag": tag_name,
            "scope": program_name or "Controller",
            "data_type": data_type,
            "value": live_val,
            "external_access": metadata.get("ExternalAccess", "Read/Write"),
            "tag_type": metadata.get("TagType", "Base"),
            "usage": metadata.get("Usage", "Local"),
            "is_alias": bool(metadata.get("AliasFor"))
        }

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
        """
        Pushes staged changes (new rungs, replaced rungs, new tags) to the controller
        as pending edits (AcceptEdits).
        """
        if not self.project:
            self.connect()

        # Step 1: Pre-read routine to verify routine type and existing instructions
        current_routine = self.read_routine(program_name, routine_name)
        routine_type = current_routine.get("type", "RLL")

        # Step 2: Enforce Hardcoded Safety Gates
        SafetyValidator.validate_proposed_rungs(
            routine_name=routine_name,
            routine_type=routine_type,
            rungs=new_rungs
        )

        # Validate any new context tags against safety gates
        if new_tags:
            for tag in new_tags:
                SafetyValidator.validate_tag_name(tag.get("name", ""))

        # Step 3: Build Compliant Partial Import L5X XML
        l5x_content = L5XBuilder.build_partial_import_envelope(
            controller_name=self.controller_name,
            program_name=program_name,
            routine_name=routine_name,
            rungs=new_rungs,
            rung_comments=new_rung_comments,
            new_tags=new_tags,
            software_revision=self.software_revision
        )

        with tempfile.NamedTemporaryFile(suffix=".L5X", mode="w", encoding="utf-8", delete=False) as tf:
            tf.write(l5x_content)
            temp_l5x = tf.name

        try:
            xpath = f"Controller/Programs/Program[@Name='{program_name}']/Routines/Routine[@Name='{routine_name}']"
            
            # Execute SDK Partial Import with ACCEPT_EDITS (creates pending zone in controller)
            self.project.partial_import_rungs_from_xml_file(
                xpath,
                insert_position,
                replace_count,
                temp_l5x,
                PartialImportOption.ACCEPT_EDITS
            )

            # Re-read routine to verify pending zone state
            post_routine = self.read_routine(program_name, routine_name)

            return {
                "status": "pending_accepted",
                "program": program_name,
                "routine": routine_name,
                "insert_position": insert_position,
                "replace_count": replace_count,
                "rungs_proposed": len(new_rungs),
                "zone_state": "pending",
                "message": (
                    f"Successfully pushed {len(new_rungs)} rungs to '{routine_name}' as pending edits. "
                    "Logic is now in accepted pending state (not executing yet). "
                    "Call 'test_edits' to test on the live controller."
                ),
                "rungs": post_routine.get("rungs", [])
            }
        finally:
            if os.path.exists(temp_l5x):
                os.remove(temp_l5x)
