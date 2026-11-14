"""
Enterprise Model Context Protocol (MCP) Server for Rockwell Studio 5000.

Provides a unified, protocol-agnostic MCP transport interface connecting AI assistants
to Rockwell Automation Studio 5000 Logix Designer:
- Feature Module A: Live Online Logic Editing (via Rockwell Logix SDK & Win32 MFC Automation)
- Feature Module B: Offline Code Generation & Translation (via .L5X XML & Compact NeutralText)
- Enterprise Error Shielding: Guarantees zero MCP transport disconnections during hallucinations or bad parameters.
"""

import os
import sys
import logging
import argparse
import functools
from typing import Dict, List, Optional, Any, Callable

# Configure logging strictly to stderr to prevent polluting the stdio JSON-RPC transport
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("studio5000_live_mcp.server")

try:
    from mcp.server.fastmcp import FastMCP
except (ImportError, ModuleNotFoundError):
    try:
        from mcp.server import MCPServer as FastMCP
    except (ImportError, ModuleNotFoundError):
        from mcp.server.mcpserver import MCPServer as FastMCP

from .adapters import (
    AdapterRouter,
    AdapterMode,
    PLCAdapterError,
    UnsupportedOperationError,
    ProjectNotFoundError
)
from .safety_validator import SafetyGateViolation
from .l5x_builder import L5XBuilder, L5XValidationError

# Initialize Global Router and FastMCP Server
router = AdapterRouter()

mcp = FastMCP(
    name="Studio 5000 Logix Assistant",
    instructions=(
        "Industrial Automation MCP server for Rockwell Studio 5000 Logix Designer. "
        "Supports both live online PLC editing via Logix SDK / Win32 automation and offline "
        ".L5X XML code generation, translation, and validation with strict industrial safety gates."
    )
)


def shield_mcp_tool(func: Callable) -> Callable:
    """
    Decorator providing an enterprise exception shield around all MCP tool entrypoints.
    Ensures that bad parameters, safety violations, or runtime PLC faults return
    structured, LLM-friendly diagnostic JSON payloads without dropping the MCP stdio stream.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except SafetyGateViolation as e:
            logger.warning(f"Safety Gate Rejection in {func.__name__}: {e}")
            return {
                "status": "SAFETY_GATE_REJECTED",
                "tool": func.__name__,
                "rule": e.rule,
                "target": e.target,
                "error": str(e),
                "remediation": "Do not attempt to bypass safety gates. Modify logic to reference standard operational tags only."
            }
        except L5XValidationError as e:
            logger.warning(f"L5X Validation Error in {func.__name__}: {e}")
            return {
                "status": "VALIDATION_FAILED",
                "tool": func.__name__,
                "error": str(e),
                "remediation": "Correct ladder logic branch syntax (ensure branches contain at least 2 legs) and XML target attributes."
            }
        except UnsupportedOperationError as e:
            logger.warning(f"Unsupported Operation in {func.__name__}: {e}")
            return {
                "status": "UNSUPPORTED_OPERATION",
                "tool": func.__name__,
                "mode": router.mode.value,
                "error": str(e),
                "remediation": e.remediation
            }
        except PLCAdapterError as e:
            logger.error(f"PLC Adapter Error in {func.__name__}: {e}", exc_info=True)
            return {
                "status": "ADAPTER_ERROR",
                "tool": func.__name__,
                "error": e.message,
                "remediation": e.remediation
            }
        except Exception as e:
            logger.error(f"Unexpected Exception in {func.__name__}: {e}", exc_info=True)
            return {
                "status": "INTERNAL_ERROR",
                "tool": func.__name__,
                "error": f"An unhandled internal error occurred: {type(e).__name__}: {e}",
                "remediation": "Verify input arguments, Studio 5000 connectivity, and file system permissions."
            }
    return wrapper


# ==========================================
# UNIVERSAL CONTEXT & ROUTING TOOLS
# ==========================================

@mcp.tool()
@shield_mcp_tool
def set_active_project(project_path: str) -> Dict[str, Any]:
    """
    Sets or switches the active project context between a live .ACD project and an offline .L5X export.
    Dynamically reconfigures the internal adapter to route subsequent commands appropriately.

    Args:
        project_path: Absolute path to the .ACD (for live online editing) or .L5X (for offline engineering).
    """
    return router.set_active_project(project_path)


@mcp.tool()
@shield_mcp_tool
def get_project_status() -> Dict[str, Any]:
    """
    Returns the current execution mode (ONLINE vs OFFLINE), loaded project path,
    SDK connection status, and list of available capabilities.
    """
    return router.get_status()


# ==========================================
# ONLINE EDIT LIFECYCLE TOOLS (Module A)
# ==========================================

@mcp.tool()
@shield_mcp_tool
def read_routine(program_name: str, routine_name: str) -> Dict[str, Any]:
    """
    Fetches the ladder logic (RLL) of a routine.
    In ONLINE mode: queries live controller scan with active zone states ('N', 'I', 'R', 'D').
    In OFFLINE mode: extracts routine directly from the loaded .L5X project file.

    Args:
        program_name: Target controller program (e.g. 'MainProgram' or 'Sonic_Mixing_Skid').
        routine_name: Target ladder routine (e.g. 'MainRoutine' or 'VALVE_CONTROL').
    """
    adapter = router.get_adapter()
    return adapter.read_routine(program_name, routine_name)


@mcp.tool()
@shield_mcp_tool
def read_tag(tag_name: str, program_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Reads tag metadata, data type, access properties, and (if online) live online value.

    Args:
        tag_name: Name of the tag to inspect (e.g. 'Pump_Speed', 'FAULT[0].11', or 'VFD:I.Active').
        program_name: Optional program name for program-scoped tags. Omit for controller-scoped tags.
    """
    adapter = router.get_adapter()
    return adapter.read_tag(tag_name, program_name)


@mcp.tool()
@shield_mcp_tool
def propose_edit(
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
    
    Hardcoded Safety Gates:
    - Rejects edits referencing tags with 'Safety_' prefix.
    - Rejects writes to Alias tags, Consumed tags, or tags with External Access = None.
    - Rejects edits to routines calling Add-On Instructions (AOIs) or Function Block Diagrams (FBD).
    - Automatically validates RLL ladder branch syntax (prevents Studio 5000 Error 12740-0).

    Args:
        program_name: Target program (e.g. 'MainProgram').
        routine_name: Target routine (must be Relay Ladder Logic).
        insert_position: 0-indexed rung number where insertion or replacement begins.
        replace_count: Number of existing rungs to replace (0 to insert new rungs).
        new_rungs: List of ladder logic strings (e.g. ["XIC(Start_PB) OTE(Run_Motor);"]).
        new_rung_comments: Optional comments matching new_rungs.
        new_tags: Optional new context tags to declare, e.g. [{"name": "StepTimer", "type": "TIMER"}].
    """
    adapter = router.get_adapter()
    return adapter.propose_edit(
        program_name=program_name,
        routine_name=routine_name,
        insert_position=insert_position,
        replace_count=replace_count,
        new_rungs=new_rungs,
        new_rung_comments=new_rung_comments,
        new_tags=new_tags
    )


@mcp.tool()
@shield_mcp_tool
def test_edits(program_name: str, routine_name: str) -> Dict[str, Any]:
    """
    Activates Test Mode for pending edits on the live controller (Studio 5000 verb 32061).
    The controller runs proposed logic while preserving original logic in memory.

    Args:
        program_name: Program containing pending edits.
        routine_name: Routine containing pending edits.
    """
    adapter = router.get_adapter()
    return adapter.test_edits(program_name, routine_name)


@mcp.tool()
@shield_mcp_tool
def untest_edits(program_name: str, routine_name: str) -> Dict[str, Any]:
    """
    Reverts controller execution back to original logic without losing pending edits (verb 32062).

    Args:
        program_name: Program containing tested edits.
        routine_name: Routine containing tested edits.
    """
    adapter = router.get_adapter()
    return adapter.untest_edits(program_name, routine_name)


@mcp.tool()
@shield_mcp_tool
def assemble_edits(program_name: str, routine_name: str, confirmed: bool = False) -> Dict[str, Any]:
    """
    Permanently finalizes pending edits on the running controller (verb 32063).
    
    CRITICAL STRUCTURAL SAFEGUARD:
    Requires explicit manual confirmation (confirmed=True). Calling with confirmed=False
    is immediately rejected without affecting the controller.

    Args:
        program_name: Program containing tested edits.
        routine_name: Routine containing tested edits.
        confirmed: Explicit confirmation flag from the human controls engineer.
    """
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
    adapter = router.online_adapter if router.mode != AdapterMode.OFFLINE else router.get_adapter()
    return adapter.assemble_edits(program_name, routine_name, confirmed=confirmed)


# ==========================================
# OFFLINE CODE GEN & TRANSLATION (Module B)
# ==========================================

@mcp.tool()
@shield_mcp_tool
def parse_l5x(file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Parses a Rockwell Studio 5000 .L5X XML export, extracting controller specifications,
    UDTs (User-Defined Types), controller tags, programs, routines, and I/O modules.

    Args:
        file_path: Optional path to the .L5X file. If omitted, parses the currently active project.
    """
    return router.offline_adapter.parse_l5x(file_path)


@mcp.tool()
@shield_mcp_tool
def translate_to_neutral_text(xml_content_or_file: str) -> Dict[str, Any]:
    """
    Translates verbose XML ladder rungs into compact Logix NeutralText (e.g. XIC(Sensor) OTE(Motor);),
    reducing token consumption by 85-92% for LLM context optimization.

    Args:
        xml_content_or_file: Raw L5X XML string, XML rung snippet, or path to an .L5X file.
    """
    return router.offline_adapter.translate_to_neutral_text(xml_content_or_file)


@mcp.tool()
@shield_mcp_tool
def generate_l5x_import(
    target_type: str,
    target_name: str,
    rungs: List[str],
    program_name: Optional[str] = "MainProgram",
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
    schema-compliant .L5X file for Studio 5000 import.
    
    Guarantees:
    - Root RSLogix5000Content contains ContainsContext="true".
    - Target element contains Use="Target" (strictly preventing Error 25134-80044178).
    - Automatically validates RLL ladder branch syntax and bracket balance (preventing Error 12740-0).

    Args:
        target_type: 'Routine' (for routine partial import) or 'AddOnInstructionDefinition' (for AOI).
        target_name: Name of routine or AOI (e.g. 'AOI_PUMP_CONTROL').
        rungs: List of ladder logic strings in NeutralText format.
        program_name: Target program for routine imports (default 'MainProgram').
        controller_name: Target controller name.
        description: Description of the routine or AOI.
        rung_comments: Optional list of comments for each rung.
        parameters: Parameter declarations for AOIs (name, type, usage, default, description).
        local_tags: Local tag declarations for AOIs.
        software_revision: Software revision (e.g. '38.00').
        output_path: Optional path to save the .L5X file directly to disk.
    """
    return router.offline_adapter.generate_l5x_import(
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


@mcp.tool()
@shield_mcp_tool
def build_aoi_l5x(
    controller_name: str,
    aoi_name: str,
    description: str = "",
    parameters: Optional[List[Dict[str, Any]]] = None,
    local_tags: Optional[List[Dict[str, Any]]] = None,
    rungs: Optional[List[str]] = None,
    rung_comments: Optional[List[str]] = None,
    software_revision: str = "38.00",
    output_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Constructs an Add-On Instruction (.L5X) XML definition file adhering 100% to Rockwell's
    import schema with Use="Target" and complete parameter/local tag specifications.
    Alias for generate_l5x_import with target_type='AddOnInstructionDefinition'.
    """
    return generate_l5x_import(
        target_type="AddOnInstructionDefinition",
        target_name=aoi_name,
        rungs=rungs or [],
        controller_name=controller_name,
        description=description,
        rung_comments=rung_comments,
        parameters=parameters,
        local_tags=local_tags,
        software_revision=software_revision,
        output_path=output_path
    )


@mcp.tool()
@shield_mcp_tool
def validate_l5x_file(file_path: str) -> Dict[str, Any]:
    """
    Validates a Rockwell Studio 5000 .L5X file against Rockwell schema requirements before import.
    Verifies Use='Target', root TargetType matching, and RLL ladder logic branch/syntax integrity.

    Args:
        file_path: Absolute or relative path to the .L5X file to inspect.
    """
    if not os.path.exists(file_path):
        return {"valid": False, "error": f"File does not exist: {file_path}"}

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    return L5XBuilder.validate_l5x(content)


# ==========================================
# SERVER ENTRYPOINT
# ==========================================

def main():
    """Server entrypoint supporting both CLI argument parsing and FastMCP execution."""
    parser = argparse.ArgumentParser(description="Studio 5000 Live & Offline MCP Server")
    parser.add_argument("--project-path", help="Initial path to active .ACD or .L5X project file")
    parser.add_argument("--acd-path", help="Alias for --project-path targeting an .ACD file")
    parser.add_argument("--l5x-path", help="Alias for --project-path targeting an .L5X file")
    args, unknown = parser.parse_known_args()

    init_path = args.project_path or args.acd_path or args.l5x_path
    if init_path:
        router.set_active_project(init_path)

    # Launch FastMCP Server over stdio
    logger.info("Starting Studio 5000 MCP Server over stdio transport...")
    mcp.run()


if __name__ == "__main__":
    main()
