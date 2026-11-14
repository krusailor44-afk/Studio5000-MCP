"""
Base PLC Adapter Interface and Data Models for Studio 5000 MCP Server.

Provides a unified, protocol-agnostic abstraction layer for interacting with
Rockwell Logix controllers across both live online connections (via the official
Logix Designer SDK) and offline engineering workflows (via .L5X XML / NeutralText).
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Literal
from dataclasses import dataclass, field
from enum import Enum


class AdapterMode(str, Enum):
    """Execution mode of the active PLC adapter."""
    ONLINE = "ONLINE"        # Live controller connected via Studio 5000 SDK / .ACD
    OFFLINE = "OFFLINE"      # Offline engineering using .L5X files and NeutralText
    UNCONFIGURED = "UNCONFIGURED"  # No active project loaded


class PLCAdapterError(Exception):
    """Base exception for all PLC adapter operations."""
    def __init__(self, message: str, remediation: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.remediation = remediation or "Review command parameters and active project state."


class UnsupportedOperationError(PLCAdapterError):
    """Raised when an operation is invalid for the active adapter mode (e.g. online edits in offline mode)."""
    pass


class ProjectNotFoundError(PLCAdapterError):
    """Raised when the target project, program, or routine does not exist."""
    pass


@dataclass
class RungData:
    """Represents a single Relay Ladder Logic (RLL) rung."""
    number: int
    logic: str
    comment: str = ""
    rung_type: Literal["N", "I", "R", "D"] = "N"  # N=Normal, I=Insert pending, R=Replace pending, D=Delete pending


@dataclass
class RoutineData:
    """Represents a routine extracted from an online controller or offline L5X."""
    name: str
    program: str
    routine_type: str = "RLL"
    rungs: List[RungData] = field(default_factory=list)
    has_pending_edits: bool = False


@dataclass
class TagData:
    """Represents a PLC tag with metadata and online value."""
    name: str
    scope: str
    data_type: str
    value: Any = None
    external_access: str = "Read/Write"
    tag_type: str = "Base"
    usage: str = "Local"
    is_alias: bool = False
    alias_for: Optional[str] = None
    description: str = ""


class PLCAdapter(ABC):
    """
    Abstract Base Class defining the standard interface for Studio 5000 PLC operations.
    Subclasses implement either live online controller interaction (via Logix SDK) or
    offline parsing, code generation, and translation (via L5X/NeutralText).
    """

    @property
    @abstractmethod
    def adapter_mode(self) -> AdapterMode:
        """Returns whether this adapter operates ONLINE or OFFLINE."""
        pass

    @property
    @abstractmethod
    def active_project_path(self) -> Optional[str]:
        """Returns the absolute path to the active .ACD or .L5X project file."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Returns True if the adapter is actively connected or ready to process requests."""
        pass

    # ==========================================
    # READ OPERATIONS (Available Online & Offline)
    # ==========================================

    @abstractmethod
    def read_routine(self, program_name: str, routine_name: str) -> Dict[str, Any]:
        """
        Reads the ladder logic of a specified routine.
        In Online mode: fetches from live controller with active zone states.
        In Offline mode: parses and extracts from the loaded .L5X file.
        """
        pass

    @abstractmethod
    def read_tag(self, tag_name: str, program_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Reads tag metadata, data type, access properties, and (if online) live value.
        """
        pass

    # ==========================================
    # ONLINE EDIT LIFECYCLE (Online Mode Only)
    # ==========================================

    @abstractmethod
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
        Pushes staged ladder logic changes to the controller as pending edits (AcceptEdits).
        Must enforce industrial safety gates and syntax validation before submission.
        """
        pass

    @abstractmethod
    def test_edits(self, program_name: str, routine_name: str) -> Dict[str, Any]:
        """
        Activates Test Mode on the live controller for pending edits.
        """
        pass

    @abstractmethod
    def untest_edits(self, program_name: str, routine_name: str) -> Dict[str, Any]:
        """
        Reverts the controller back to scanning the original logic without committing changes.
        """
        pass

    @abstractmethod
    def assemble_edits(self, program_name: str, routine_name: str, confirmed: bool = False) -> Dict[str, Any]:
        """
        Permanently finalizes pending edits on the live controller.
        Requires explicit human-in-the-loop confirmation (confirmed=True).
        """
        pass

    # ==========================================
    # OFFLINE CODE GENERATION & TRANSLATION
    # ==========================================

    @abstractmethod
    def parse_l5x(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Ingests an .L5X XML file and extracts controller metadata, UDTs, tags, and routines.
        """
        pass

    @abstractmethod
    def translate_to_neutral_text(self, xml_content_or_file: str) -> Dict[str, Any]:
        """
        Converts verbose XML ladder rungs into compact Logix NeutralText (e.g. XIC(Sensor) OTE(Motor);)
        to optimize LLM context usage.
        """
        pass

    @abstractmethod
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
        Packages AI-generated NeutralText ladder rungs into a strictly formatted,
        schema-compliant .L5X file for Studio 5000 import.
        """
        pass
