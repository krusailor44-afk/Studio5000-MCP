"""
Safety Validator for Studio 5000 Live MCP Server.

Implements hardcoded, unbypassable safety gates for online PLC logic edits:
1. Deny write access or edits to tags with 'Safety_' prefix, alias tags, consumed tags,
   or tags with External Access set to None.
2. Deny edits to routines containing Add-On Instructions (AOIs) or Function Block Diagrams (FBD)
   where live online editing is unsafe or unsupported by the controller context.
"""

import re
from typing import Dict, List, Optional, Set, Any


class SafetyGateViolation(Exception):
    """Raised when an operation violates a hardcoded PLC safety gate."""
    def __init__(self, rule: str, target: str, reason: str):
        self.rule = rule
        self.target = target
        self.reason = reason
        super().__init__(f"SAFETY GATE REJECTION [{rule}] on '{target}': {reason}")


class SafetyValidator:
    """Enforces industrial safety boundaries for live controller interactions."""

    # Regex matching instruction calls in Rockwell Ladder Logic (RLL) text:
    # Matches patterns like: XIC(Tag1) or BST XIC(Tag1) NXB XIC(Tag2) BND OTE(OutTag)
    INSTRUCTION_PATTERN = re.compile(r"([A-Za-z0-9_]+)\s*\(([^)]*)\)")
    
    # Standard Rockwell base ladder instructions (non-AOI)
    STANDARD_INSTRUCTIONS: Set[str] = {
        "XIC", "XIO", "OTE", "OTL", "OTU", "ONS", "OSR", "OSF",
        "TON", "TOF", "RTO", "CTU", "CTD", "RES",
        "EQU", "NEQ", "LES", "LEQ", "GRT", "GEQ", "LIM", "MEQ",
        "MOV", "MVM", "COP", "CPS", "FLL", "CLR",
        "ADD", "SUB", "MUL", "DIV", "MOD", "SQR", "NEG", "ABS",
        "AND", "OR", "XOR", "NOT",
        "JMP", "LBL", "JSR", "RET", "SBR", "TND", "MCR",
        "BSL", "BSR", "FFL", "FFU", "LFL", "LFU",
        "FAL", "FSC", "AVE", "STD", "SRT",
        "BTD", "DCD", "ENC", "SWPB",
        "GSV", "SSV", "MSG", "ALMA", "ALMD"
    }

    @classmethod
    def validate_tag_name(cls, tag_name: str) -> None:
        """Denies access if tag starts with Safety_ (case-insensitive)."""
        clean_name = tag_name.strip()
        # Extract base tag name before any array index or struct member
        base_name = re.split(r"[.\[]", clean_name)[0]
        
        if base_name.lower().startswith("safety_"):
            raise SafetyGateViolation(
                rule="PROHIBITED_SAFETY_TAG",
                target=tag_name,
                reason="Direct edits or writes to safety-instrumented tags (prefixed with 'Safety_') are strictly forbidden."
            )

    @classmethod
    def validate_tag_metadata(cls, tag_name: str, metadata: Dict[str, Any]) -> None:
        """
        Validates tag attributes against hardcoded safety restrictions:
        - Must not be an Alias tag
        - Must not be a Consumed tag
        - ExternalAccess must not be 'None'
        """
        cls.validate_tag_name(tag_name)

        # 1. Check for Alias Tag
        if metadata.get("is_alias") or metadata.get("alias_for") or metadata.get("TagType") == "Alias":
            target_alias = metadata.get("alias_for", "unknown")
            raise SafetyGateViolation(
                rule="PROHIBITED_ALIAS_TAG",
                target=tag_name,
                reason=f"Writing to alias tags is forbidden due to indirect addressing hazards (aliases '{target_alias}')."
            )

        # 2. Check for Consumed Tag
        usage = str(metadata.get("usage", metadata.get("Usage", ""))).strip().lower()
        if usage == "consumed":
            raise SafetyGateViolation(
                rule="PROHIBITED_CONSUMED_TAG",
                target=tag_name,
                reason="Writing to consumed tags is prohibited because their values are cyclically overwritten by a producing controller."
            )

        # 3. Check External Access
        ext_access = str(metadata.get("external_access", metadata.get("ExternalAccess", ""))).strip().lower()
        if ext_access in ("none", "0"):
            raise SafetyGateViolation(
                rule="PROHIBITED_EXTERNAL_ACCESS_NONE",
                target=tag_name,
                reason="Tag is configured with External Access = None; edits via external interfaces are prohibited."
            )

    @classmethod
    def validate_routine_type(cls, routine_name: str, routine_type: str) -> None:
        """Rejects routines that are not Ladder Logic (RLL), e.g. FBD, SFC, ST."""
        norm_type = routine_type.strip().upper()
        if norm_type != "RLL":
            raise SafetyGateViolation(
                rule="UNSUPPORTED_ROUTINE_TYPE",
                target=routine_name,
                reason=f"Routine type is '{norm_type}'. Online edits are strictly restricted to Relay Ladder Logic (RLL) routines. Function Block Diagrams (FBD) and Sequential Function Charts (SFC) are denied."
            )

    @classmethod
    def extract_operands_from_rung(cls, rung_text: str) -> List[str]:
        """Extracts all variable/tag operands referenced within a rung string."""
        operands = []
        for match in cls.INSTRUCTION_PATTERN.finditer(rung_text):
            args_str = match.group(2)
            if not args_str:
                continue
            # Split comma-separated arguments
            raw_args = [arg.strip() for arg in args_str.split(",")]
            for arg in raw_args:
                # Exclude pure numeric literals, question marks, and string literals
                if arg and not arg.startswith('"') and not arg.startswith("'") and not arg.replace(".", "", 1).isdigit() and arg != "?":
                    operands.append(arg)
        return operands

    @classmethod
    def extract_instructions_from_rung(cls, rung_text: str) -> List[str]:
        """Extracts instruction mnemonics called in the rung."""
        instructions = []
        for match in cls.INSTRUCTION_PATTERN.finditer(rung_text):
            instructions.append(match.group(1).strip().upper())
        return instructions

    @classmethod
    def validate_proposed_rungs(
        cls,
        routine_name: str,
        routine_type: str,
        rungs: List[str],
        known_aois: Optional[Set[str]] = None,
        tag_metadata_map: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> None:
        """
        Comprehensive check on proposed online rung edits:
        1. Confirms routine type is RLL.
        2. Ensures no Add-On Instructions (AOIs) are invoked.
        3. Validates all referenced tag operands against safety gates.
        """
        # 1. Routine type check
        cls.validate_routine_type(routine_name, routine_type)

        aoi_set = {a.upper() for a in known_aois} if known_aois else set()
        tag_meta = tag_metadata_map or {}

        for rung_idx, rung in enumerate(rungs):
            # Check instructions for AOIs
            instructions = cls.extract_instructions_from_rung(rung)
            for inst in instructions:
                if inst in aoi_set or (inst not in cls.STANDARD_INSTRUCTIONS and not inst.startswith("BRANCH")):
                    # If it's a known AOI or a non-standard custom instruction
                    raise SafetyGateViolation(
                        rule="PROHIBITED_AOI_INSTRUCTION",
                        target=f"{routine_name}:Rung_{rung_idx}",
                        reason=f"Instruction '{inst}' is an Add-On Instruction (AOI) or custom non-standard block. Online edits to routines containing or calling AOIs are denied."
                    )

            # Check operands for safety tag restrictions
            operands = cls.extract_operands_from_rung(rung)
            for operand in operands:
                # Clean base tag name
                base_tag = re.split(r"[.\[]", operand)[0]
                cls.validate_tag_name(base_tag)

                if base_tag in tag_meta:
                    cls.validate_tag_metadata(base_tag, tag_meta[base_tag])
