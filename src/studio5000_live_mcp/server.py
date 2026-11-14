"""
Studio 5000 Live MCP Server.

Provides a Model Context Protocol (MCP) server enabling AI models to safely inspect,
propose, test, untest, and assemble online PLC edits in Rockwell Studio 5000 Logix Designer.
"""

import os
import sys
import argparse
from typing import Dict, List, Optional, Any
try:
    from mcp.server.fastmcp import FastMCP
except (ImportError, ModuleNotFoundError):
    try:
        from mcp.server import MCPServer as FastMCP
    except (ImportError, ModuleNotFoundError):
        from mcp.server.mcpserver import MCPServer as FastMCP

from .sdk_client import Studio5000SDKClient, SDK_AVAILABLE
from .safety_validator import SafetyValidator, SafetyGateViolation
from .win32_lifecycle import Win32LifecycleDriver

# Initialize FastMCP Server
mcp = FastMCP(
    name="Studio 5000 Live PLC Assistant",
    instructions=(
        "Industrial Automation MCP server for Rockwell Studio 5000 Logix Designer online logic editing. "
        "Allows reading live routines/tags and managing the online edit lifecycle (propose, test, untest, assemble) "
        "with hardcoded industrial safety gates."
    )
)

# Global Client Instance
_client: Optional[Studio5000SDKClient] = None


def get_client() -> Studio5000SDKClient:
    """Returns the initialized SDK client instance."""
    global _client
    if _client is None:
        acd_path = os.environ.get("STUDIO5000_ACD_PATH")
        if not acd_path:
            raise ValueError(
                "No .ACD project path configured. Set the STUDIO5000_ACD_PATH environment variable "
                "or start the server with --acd-path <path_to_acd>."
            )
        _client = Studio5000SDKClient(acd_path)
    return _client


# ==========================================
# READ TOOLS
# ==========================================

@mcp.tool()
def read_routine(program_name: str, routine_name: str) -> Dict[str, Any]:
    """
    Fetches the current ladder logic (RLL) of a specified routine so the AI can analyze
    it before proposing any online edit.
    
    Args:
        program_name: Name of the controller program (e.g. 'MainProgram').
        routine_name: Name of the ladder routine (e.g. 'MainRoutine').
        
    Returns:
        Structured routine content including rung numbers, comments, logic text, and pending state.
    """
    client = get_client()
    return client.read_routine(program_name, routine_name)


@mcp.tool()
def read_tag(tag_name: str, program_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetches the live value, data type, and access properties of a PLC tag while online.
    
    Args:
        tag_name: Name of the tag to read (e.g. 'Pump_Speed' or 'Inlet_Valve.Open').
        program_name: Optional program name for program-scoped tags. Omit for controller-scoped tags.
        
    Returns:
        Tag metadata, data type, scope, and live online value.
    """
    client = get_client()
    return client.read_tag(tag_name, program_name)


# ==========================================
# ONLINE EDIT LIFECYCLE TOOLS
# ==========================================

@mcp.tool()
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
    Pushes staged ladder logic changes (new rungs, replaced rungs, new context tags)
    to the live controller as pending edits (AcceptEdits).
    
    Enforces strict safety gates:
    - Denies writes or edits referencing tags with 'Safety_' prefix.
    - Denies writes to Alias tags, Consumed tags, or tags with External Access = None.
    - Denies edits to routines containing Add-On Instructions (AOIs) or Function Block Diagrams (FBD).
    
    Args:
        program_name: Target program (e.g. 'MainProgram').
        routine_name: Target routine (must be RLL ladder logic).
        insert_position: 0-indexed rung position where edits begin.
        replace_count: Number of existing rungs to replace (0 to insert without replacing).
        new_rungs: List of Rockwell ladder logic strings (e.g. ["XIC(Start_PB)OTE(Run_Motor);"]).
        new_rung_comments: Optional list of comments matching new_rungs.
        new_tags: Optional list of new context tags to declare, e.g. [{"name": "StepTimer", "type": "TIMER"}].
        
    Returns:
        Pending edit state and details of the staged rungs.
    """
    client = get_client()
    return client.propose_edit(
        program_name=program_name,
        routine_name=routine_name,
        insert_position=insert_position,
        replace_count=replace_count,
        new_rungs=new_rungs,
        new_rung_comments=new_rung_comments,
        new_tags=new_tags
    )


@mcp.tool()
def test_edits(program_name: str, routine_name: str) -> Dict[str, Any]:
    """
    Activates Test Mode for pending edits on the live controller.
    
    In test mode:
    - The new logic runs on the physical controller scan.
    - The original logic remains buffered and can be reverted immediately with 'untest_edits'.
    
    Args:
        program_name: Program containing pending edits.
        routine_name: Routine containing pending edits.
    """
    # Trigger MFC Test command 32061 via Win32 Lifecycle Driver
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
            "Verify process behavior carefully. Call 'untest_edits' to revert, or 'assemble_edits' to finalize."
        )
    }


@mcp.tool()
def untest_edits(program_name: str, routine_name: str) -> Dict[str, Any]:
    """
    Reverts the controller back to the original ladder logic if tests fail or show unexpected behavior.
    
    In untest mode:
    - The proposed edits stop executing.
    - The controller immediately resumes scanning the original logic.
    - The pending edits remain buffered as accepted zones in Studio 5000.
    
    Args:
        program_name: Program containing tested edits.
        routine_name: Routine containing tested edits.
    """
    # Trigger MFC Untest command 32062 via Win32 Lifecycle Driver
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


@mcp.tool()
def assemble_edits(program_name: str, routine_name: str, confirmed: bool = False) -> Dict[str, Any]:
    """
    Finalizes the pending edits, permanently overwriting the original controller logic.
    
    CRITICAL SAFEGUARD:
    Requires explicit manual human-in-the-loop confirmation (confirmed=True).
    Calling with confirmed=False will be rejected immediately without modifying the PLC.
    
    Args:
        program_name: Program containing tested edits to finalize.
        routine_name: Routine containing tested edits to finalize.
        confirmed: Explicit safety confirmation flag. Must be set to True by the operator.
    """
    if not confirmed:
        return {
            "status": "REJECTED_BY_SAFEGUARD",
            "error": (
                "HUMAN-IN-THE-LOOP SAFEGUARD TRIGGERED: Assembling edits permanently commits changes "
                "to the running PLC and deletes the original logic. You must review tested behavior with the "
                "lead engineer and explicitly pass confirmed=True to finalize."
            ),
            "confirmed": False
        }

    # Trigger MFC Assemble command 32063 via Win32 Lifecycle Driver
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


def main():
    """Server entrypoint parsing CLI arguments and launching stdio MCP service."""
    parser = argparse.ArgumentParser(description="Studio 5000 Live MCP Server")
    parser.add_argument("--acd-path", help="Path to the active Studio 5000 .ACD project file")
    args = parser.parse_args()

    if args.acd_path:
        os.environ["STUDIO5000_ACD_PATH"] = os.path.abspath(args.acd_path)

    # Run the FastMCP server over standard I/O
    mcp.run()


if __name__ == "__main__":
    main()
