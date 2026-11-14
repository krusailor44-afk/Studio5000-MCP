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
        "EQ", "NE", "LT", "LE", "GT", "GE",
        "MOV", "MOVE", "MVM", "COP", "CPS", "FLL", "CLR",
        "ADD", "SUB", "MUL", "DIV", "MOD", "SQR", "NEG", "ABS", "TRN",
        "AND", "OR", "XOR", "NOT",
        "CPT", "PID",
        "LN", "LOG", "SIN", "COS", "TAN", "ASN", "ACS", "ATN", "DEG", "RAD",
        "JMP", "LBL", "JSR", "RET", "SBR", "TND", "MCR",
        "BSL", "BSR", "FFL", "FFU", "LFL", "LFU",
        "FAL", "FSC", "AVE", "STD", "SRT",
        "BTD", "DCD", "ENC", "SWPB",
        "SQI", "SQO", "SQL", "TOD", "FRD", "SIZE",
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

    @staticmethod
    def _split_top_level_commas(s: str) -> List[str]:
        """Splits an argument string by comma only at the outermost parenthesis/bracket depth."""
        parts = []
        cur = []
        p_depth = 0
        b_depth = 0
        for ch in s:
            if ch == '(':
                p_depth += 1
            elif ch == ')':
                p_depth = max(0, p_depth - 1)
            elif ch == '[':
                b_depth += 1
            elif ch == ']':
                b_depth = max(0, b_depth - 1)
            elif ch == ',' and p_depth == 0 and b_depth == 0:
                parts.append("".join(cur))
                cur = []
                continue
            cur.append(ch)
        if cur:
            parts.append("".join(cur))
        return parts

    @classmethod
    def parse_instructions_and_args(cls, rung_text: str) -> List[tuple[str, str]]:
        """
        Parses all instruction calls in a rung, balancing parentheses even for complex
        expressions (e.g. CPT arithmetic, PID, array indexing).
        Returns a list of (instruction_name, args_string) tuples.
        """
        results = []
        i = 0
        n = len(rung_text)
        while i < n:
            m = re.search(r'\b([A-Za-z0-9_]+)\s*\(', rung_text[i:])
            if not m:
                break
            inst_name = m.group(1).upper()
            open_paren = i + m.end() - 1

            # Match closing parenthesis by depth
            depth = 1
            j = open_paren + 1
            while j < n and depth > 0:
                ch = rung_text[j]
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                j += 1

            if depth == 0:
                args_str = rung_text[open_paren + 1:j - 1]
                results.append((inst_name, args_str))
                i = j
            else:
                break
        return results

    @classmethod
    def extract_operands_from_rung(cls, rung_text: str) -> List[str]:
        """Extracts all variable/tag operands referenced within a rung string."""
        operands = []
        for inst, args_str in cls.parse_instructions_and_args(rung_text):
            if not args_str:
                continue

            if inst == "CPT":
                # First argument is destination tag
                parts = args_str.split(",", 1)
                dest = parts[0].strip()
                if dest and not dest.isdigit():
                    operands.append(dest)
                if len(parts) > 1:
                    # In arithmetic expression, extract all identifier tokens (tags)
                    expr = parts[1]
                    math_func = {"SIN", "COS", "TAN", "ASN", "ACS", "ATN", "SQR", "LN", "LOG", "DEG", "RAD", "TRN", "ABS"}
                    for token in re.findall(r'[A-Za-z_][A-Za-z0-9_.]*', expr):
                        if token.upper() not in math_func and not token.replace(".", "", 1).isdigit():
                            operands.append(token)
            else:
                raw_args = cls._split_top_level_commas(args_str)
                for arg in raw_args:
                    clean_arg = arg.strip()
                    if (clean_arg and not clean_arg.startswith('"') and not clean_arg.startswith("'")
                            and not clean_arg.replace(".", "", 1).isdigit() and clean_arg != "?"):
                        operands.append(clean_arg)
        return operands

    @classmethod
    def extract_instructions_from_rung(cls, rung_text: str) -> List[str]:
        """Extracts instruction mnemonics called in the rung."""
        return [inst for inst, _ in cls.parse_instructions_and_args(rung_text)]

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
