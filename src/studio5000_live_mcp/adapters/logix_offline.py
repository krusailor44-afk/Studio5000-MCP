"""
Logix Offline Adapter for Studio 5000 MCP Server.

Provides offline code generation, XML parsing, and NeutralText translation:
1. parse_l5x: Ingests Rockwell .L5X XML exports and extracts controller metadata,
   UDTs, tags, programs, routines, and hardware modules.
2. translate_to_neutral_text: Converts verbose XML ladder rungs into compact
   Logix NeutralText syntax to optimize LLM context usage.
3. generate_l5x_import: Packages AI-generated NeutralText into strictly formatted,
   schema-compliant .L5X files for error-free Studio 5000 import.
4. Offline tag and routine queries directly against loaded .L5X files.
"""

import os
import re
import logging
from typing import Dict, List, Optional, Any
import xml.etree.ElementTree as ET

from .base import PLCAdapter, AdapterMode, UnsupportedOperationError, PLCAdapterError
from ..l5x_builder import L5XBuilder, L5XValidationError
from ..safety_validator import SafetyValidator

logger = logging.getLogger("studio5000_live_mcp.adapters.offline")


class LogixOfflineAdapter(PLCAdapter):
    """
    Adapter implementing offline code generation, .L5X parsing, and NeutralText
    translation without requiring a physical controller connection or Logix SDK.
    """

    def __init__(self, l5x_path: Optional[str] = None):
        self._l5x_path: Optional[str] = os.path.abspath(l5x_path) if l5x_path else None
        self._cached_tree: Optional[ET.ElementTree] = None
        self._cached_root: Optional[ET.Element] = None
        if self._l5x_path and os.path.exists(self._l5x_path):
            self._load_tree(self._l5x_path)

    @property
    def adapter_mode(self) -> AdapterMode:
        return AdapterMode.OFFLINE

    @property
    def active_project_path(self) -> Optional[str]:
        return self._l5x_path

    @property
    def is_connected(self) -> bool:
        return self._cached_root is not None

    def set_project(self, l5x_path: str) -> None:
        """Loads and caches an offline .L5X project file."""
        abs_path = os.path.abspath(l5x_path)
        if not os.path.exists(abs_path):
            raise PLCAdapterError(
                f"L5X file does not exist: {abs_path}",
                remediation="Verify the file path exists and is an exported Rockwell .L5X document."
            )
        self._load_tree(abs_path)
        self._l5x_path = abs_path
        logger.info(f"LogixOfflineAdapter loaded L5X: {self._l5x_path}")

    def _load_tree(self, path: str) -> None:
        try:
            self._cached_tree = ET.parse(path)
            self._cached_root = self._cached_tree.getroot()
        except ET.ParseError as e:
            raise PLCAdapterError(
                f"Invalid XML syntax in L5X file '{path}': {e}",
                remediation="Ensure file is an uncorrupted UTF-8 Rockwell Logix XML document."
            )

    # ==========================================
    # OFFLINE PARSING & INSPECTION
    # ==========================================

    def parse_l5x(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Parses an .L5X XML file and extracts controller configuration, UDTs, tags,
        programs, routines, and I/O modules into structured JSON.
        """
        target_path = file_path or self._l5x_path
        if not target_path:
            raise PLCAdapterError(
                "No L5X file path specified and no active L5X project is loaded.",
                remediation="Call parse_l5x with a valid file_path or call set_active_project first."
            )

        abs_path = os.path.abspath(target_path)
        if not os.path.exists(abs_path):
            raise PLCAdapterError(f"File not found: {abs_path}")

        try:
            tree = ET.parse(abs_path)
            root = tree.getroot()
        except Exception as e:
            raise PLCAdapterError(f"Failed to parse L5X XML: {e}")

        # 1. Controller Metadata
        target_name = root.attrib.get("TargetName", "")
        target_type = root.attrib.get("TargetType", "")
        software_revision = root.attrib.get("SoftwareRevision", "")
        schema_revision = root.attrib.get("SchemaRevision", "")

        controller_elem = root.find(".//Controller")
        controller_name = controller_elem.attrib.get("Name", target_name) if controller_elem is not None else target_name
        processor_type = controller_elem.attrib.get("ProcessorType", "") if controller_elem is not None else ""

        # 2. Data Types (UDTs)
        udts = []
        for dt_elem in root.findall(".//DataType"):
            dt_name = dt_elem.attrib.get("Name", "")
            desc_elem = dt_elem.find("Description")
            desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""
            members = []
            for mem in dt_elem.findall(".//Member"):
                members.append({
                    "name": mem.attrib.get("Name", ""),
                    "data_type": mem.attrib.get("DataType", ""),
                    "dimension": mem.attrib.get("Dimension", "0"),
                    "radix": mem.attrib.get("Radix", "Decimal")
                })
            udts.append({
                "name": dt_name,
                "description": desc,
                "member_count": len(members),
                "members": members
            })

        # 3. Controller-Scoped Tags
        controller_tags = []
        for tag in root.findall("./Controller/Tags/Tag") or root.findall(".//Tags[@Use='Context']/Tag"):
            name = tag.attrib.get("Name", "")
            desc_elem = tag.find("Description")
            desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""
            controller_tags.append({
                "name": name,
                "data_type": tag.attrib.get("DataType", ""),
                "tag_type": tag.attrib.get("TagType", "Base"),
                "dimensions": tag.attrib.get("Dimensions", "0"),
                "constant": tag.attrib.get("Constant", "false"),
                "external_access": tag.attrib.get("ExternalAccess", "Read/Write"),
                "description": desc
            })

        # 4. Programs & Routines
        programs = []
        for prog in root.findall(".//Program"):
            p_name = prog.attrib.get("Name", "")
            p_type = prog.attrib.get("Type", "Normal")
            main_routine = prog.attrib.get("MainRoutineName", "")
            fault_routine = prog.attrib.get("FaultRoutineName", "")

            routines = []
            for rtn in prog.findall(".//Routine"):
                r_name = rtn.attrib.get("Name", "")
                r_type = rtn.attrib.get("Type", "RLL")
                rll_content = rtn.find("RLLContent")
                rung_count = len(rll_content.findall("Rung")) if rll_content is not None else 0
                routines.append({
                    "name": r_name,
                    "type": r_type,
                    "rung_count": rung_count
                })

            p_tags = len(prog.findall(".//Tag"))
            programs.append({
                "name": p_name,
                "type": p_type,
                "main_routine": main_routine,
                "fault_routine": fault_routine,
                "routine_count": len(routines),
                "routines": routines,
                "program_tag_count": p_tags
            })

        # 5. Add-On Instruction Definitions (AOIs)
        aois = []
        for aoi in root.findall(".//AddOnInstructionDefinition"):
            aoi_name = aoi.attrib.get("Name", "")
            revision = aoi.attrib.get("Revision", "")
            desc_elem = aoi.find("Description")
            desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""
            param_count = len(aoi.findall(".//Parameter"))
            aois.append({
                "name": aoi_name,
                "revision": revision,
                "description": desc,
                "parameter_count": param_count
            })

        # 6. Hardware Modules
        modules = []
        for mod in root.findall(".//Module"):
            modules.append({
                "name": mod.attrib.get("Name", ""),
                "catalog_number": mod.attrib.get("CatalogNumber", ""),
                "slot": mod.attrib.get("Slot", ""),
                "parent_module": mod.attrib.get("ParentModule", "")
            })

        return {
            "status": "success",
            "file_path": abs_path,
            "target_type": target_type,
            "target_name": target_name,
            "controller_name": controller_name,
            "processor_type": processor_type,
            "software_revision": software_revision,
            "udt_count": len(udts),
            "udts": udts,
            "controller_tag_count": len(controller_tags),
            "controller_tags": controller_tags[:50],  # Return top 50 in summary
            "program_count": len(programs),
            "programs": programs,
            "aoi_count": len(aois),
            "aois": aois,
            "module_count": len(modules),
            "modules": modules
        }

    # ==========================================
    # NEUTRALTEXT TRANSLATION (Token Optimization)
    # ==========================================

    def translate_to_neutral_text(self, xml_content_or_file: str) -> Dict[str, Any]:
        """
        Converts verbose XML ladder rungs into compact Logix NeutralText.
        Strips verbose XML wrappers to save up to 90% LLM context window tokens.
        """
        raw_xml = xml_content_or_file.strip()
        if os.path.exists(raw_xml):
            with open(raw_xml, "r", encoding="utf-8") as f:
                raw_xml = f.read()

        try:
            root = ET.fromstring(raw_xml)
        except Exception:
            # Wrap snippet if not root
            try:
                root = ET.fromstring(f"<Root>{raw_xml}</Root>")
            except Exception as e:
                raise PLCAdapterError(f"Failed to parse XML content for NeutralText translation: {e}")

        rungs_output = []
        raw_rungs = root.findall(".//Rung")
        if not raw_rungs and root.tag == "Rung":
            raw_rungs = [root]

        for rung in raw_rungs:
            num = rung.attrib.get("Number", "?")
            rung_type = rung.attrib.get("Type", "N")
            comment_elem = rung.find("Comment")
            comment = comment_elem.text.strip() if comment_elem is not None and comment_elem.text else ""
            text_elem = rung.find("Text")
            logic = text_elem.text.strip() if text_elem is not None and text_elem.text else ""

            # Format compact NeutralText line
            lines = []
            if comment:
                lines.append(f"// Rung {num}: {comment}")
            type_indicator = f"[{rung_type}] " if rung_type != "N" else ""
            lines.append(f"Rung {num}: {type_indicator}{logic}")
            rungs_output.append("\n".join(lines))

        compact_neutral_text = "\n\n".join(rungs_output)
        xml_len = len(raw_xml)
        text_len = len(compact_neutral_text)
        reduction_pct = round(((xml_len - text_len) / xml_len) * 100, 1) if xml_len > 0 else 0.0

        return {
            "status": "success",
            "rung_count": len(raw_rungs),
            "neutral_text": compact_neutral_text,
            "metrics": {
                "xml_characters": xml_len,
                "neutral_text_characters": text_len,
                "token_reduction_percent": reduction_pct
            }
        }

    # ==========================================
    # CODE GENERATION & L5X PACKAGING
    # ==========================================

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
        """
        Packages AI-generated NeutralText ladder logic into a strictly formatted,
        schema-compliant Rockwell .L5X file for error-free Studio 5000 import.
        """
        norm_type = target_type.strip().lower()
        if "aoi" in norm_type or "addon" in norm_type or norm_type == "addoninstructiondefinition":
            # Build AOI definition envelope
            xml_content = L5XBuilder.build_aoi_envelope(
                controller_name=controller_name,
                aoi_name=target_name,
                description=description,
                parameters=parameters,
                local_tags=local_tags,
                rungs=rungs,
                rung_comments=rung_comments,
                software_revision=software_revision
            )
            ret_target_type = "AddOnInstructionDefinition"
        else:
            # Build Routine partial import envelope
            prog = program_name or "MainProgram"
            xml_content = L5XBuilder.build_partial_import_envelope(
                controller_name=controller_name,
                program_name=prog,
                routine_name=target_name,
                rungs=rungs,
                rung_comments=rung_comments,
                software_revision=software_revision
            )
            ret_target_type = "Routine"

        result = {
            "status": "success",
            "target_type": ret_target_type,
            "target_name": target_name,
            "rung_count": len(rungs),
            "xml_characters": len(xml_content)
        }

        if output_path:
            save_res = L5XBuilder.save_l5x_file(output_path, xml_content)
            result["file_path"] = save_res["file_path"]
            result["bytes_written"] = save_res["bytes_written"]
        else:
            result["xml_content"] = xml_content

        return result

    # ==========================================
    # OFFLINE READ OPERATIONS
    # ==========================================

    def read_routine(self, program_name: str, routine_name: str) -> Dict[str, Any]:
        """Extracts routine ladder logic from the loaded offline .L5X file."""
        if self._cached_root is None:
            raise PLCAdapterError("No offline .L5X project loaded. Call set_active_project first.")

        # Find routine node
        xpath = f".//Program[@Name='{program_name}']//Routine[@Name='{routine_name}']"
        routine_elem = self._cached_root.find(xpath)
        if routine_elem is None:
            # Try finding routine anywhere if program scope was generic
            routine_elem = self._cached_root.find(f".//Routine[@Name='{routine_name}']")

        if routine_elem is None:
            raise PLCAdapterError(
                f"Routine '{routine_name}' not found in loaded L5X (program='{program_name}').",
                remediation="Use parse_l5x to inspect available programs and routines in the file."
            )

        rll_content = routine_elem.find("RLLContent")
        rungs_data = []
        if rll_content is not None:
            for rung in rll_content.findall("Rung"):
                num = int(rung.attrib.get("Number", 0))
                r_type = rung.attrib.get("Type", "N")
                comment_elem = rung.find("Comment")
                comment = comment_elem.text.strip() if comment_elem is not None and comment_elem.text else ""
                text_elem = rung.find("Text")
                logic = text_elem.text.strip() if text_elem is not None and text_elem.text else ""
                rungs_data.append({
                    "number": num,
                    "type": r_type,
                    "comment": comment,
                    "logic": logic
                })

        return {
            "source": "offline_l5x",
            "file": self._l5x_path,
            "program": program_name,
            "routine": routine_name,
            "type": routine_elem.attrib.get("Type", "RLL"),
            "rung_count": len(rungs_data),
            "rungs": rungs_data
        }

    def read_tag(self, tag_name: str, program_name: Optional[str] = None) -> Dict[str, Any]:
        """Extracts tag definition and initial data from the loaded offline .L5X file."""
        if self._cached_root is None:
            raise PLCAdapterError("No offline .L5X project loaded. Call set_active_project first.")

        if program_name:
            tag_elem = self._cached_root.find(f".//Program[@Name='{program_name}']//Tag[@Name='{tag_name}']")
            scope = program_name
        else:
            tag_elem = self._cached_root.find(f".//Controller/Tags/Tag[@Name='{tag_name}']")
            scope = "Controller"

        if tag_elem is None:
            tag_elem = self._cached_root.find(f".//Tag[@Name='{tag_name}']")
            scope = "Global"

        if tag_elem is None:
            raise PLCAdapterError(
                f"Tag '{tag_name}' not found in loaded L5X file.",
                remediation="Use parse_l5x to inspect declared tags."
            )

        desc_elem = tag_elem.find("Description")
        desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""

        # Default data extraction
        val_elem = tag_elem.find(".//DataValue")
        initial_val = val_elem.attrib.get("Value") if val_elem is not None else None

        return {
            "source": "offline_l5x",
            "tag": tag_name,
            "scope": scope,
            "data_type": tag_elem.attrib.get("DataType", "UNKNOWN"),
            "initial_value": initial_val,
            "external_access": tag_elem.attrib.get("ExternalAccess", "Read/Write"),
            "tag_type": tag_elem.attrib.get("TagType", "Base"),
            "is_alias": bool(tag_elem.attrib.get("AliasFor")),
            "description": desc
        }

    # ==========================================
    # UNSUPPORTED ONLINE OPERATIONS
    # ==========================================

    def propose_edit(self, *args, **kwargs) -> Dict[str, Any]:
        raise UnsupportedOperationError(
            "propose_edit is an online controller operation and is unavailable in offline .L5X mode. "
            "To push live edits to a controller, load a live .ACD project via set_active_project or the SDK. "
            "To generate offline logic, call generate_l5x_import instead."
        )

    def test_edits(self, program_name: str, routine_name: str) -> Dict[str, Any]:
        raise UnsupportedOperationError(
            "test_edits requires an active online controller connection (Studio 5000 in REM Run/Prog mode). "
            "This operation is not supported when working with offline .L5X files."
        )

    def untest_edits(self, program_name: str, routine_name: str) -> Dict[str, Any]:
        raise UnsupportedOperationError(
            "untest_edits requires an active online controller connection. "
            "This operation is not supported when working with offline .L5X files."
        )

    def assemble_edits(self, program_name: str, routine_name: str, confirmed: bool = False) -> Dict[str, Any]:
        raise UnsupportedOperationError(
            "assemble_edits permanently commits pending edits on a running controller via SDK. "
            "This operation is not supported when working with offline .L5X files."
        )
