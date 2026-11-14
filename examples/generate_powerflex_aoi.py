"""
Example: Generating a Schema-Compliant Add-On Instruction (.L5X)
Demonstrates using the Studio 5000 MCP offline tools to programmatically build an
enterprise Add-On Instruction with parameters, local tags, and verified ladder logic.
"""

import os
from studio5000_live_mcp.l5x_builder import L5XBuilder

def main():
    print("Building PowerFlex 525 VFD Control AOI...")

    parameters = [
        {"name": "E_Stop_OK", "type": "BOOL", "usage": "Input", "required": True, "visible": True, "default": "0", "description": "Emergency Stop Healthy Permissive"},
        {"name": "Start_PB", "type": "BOOL", "usage": "Input", "required": True, "visible": True, "default": "0", "description": "Manual Start Pushbutton"},
        {"name": "Stop_PB", "type": "BOOL", "usage": "Input", "required": True, "visible": True, "default": "0", "description": "Manual Stop Pushbutton"},
        {"name": "Speed_SP_Hz", "type": "REAL", "usage": "Input", "required": True, "visible": True, "default": "60.0", "description": "Target Operating Frequency in Hz"},
        {"name": "Min_Speed_Hz", "type": "REAL", "usage": "Input", "required": True, "visible": True, "default": "15.0", "description": "Minimum Clamped Frequency"},
        {"name": "Max_Speed_Hz", "type": "REAL", "usage": "Input", "required": True, "visible": True, "default": "60.0", "description": "Maximum Clamped Frequency"},
        {"name": "Drive_Start_Out", "type": "BOOL", "usage": "Output", "required": True, "visible": True, "default": "0", "description": "Start command to VFD:O.Start"},
        {"name": "Drive_Stop_Out", "type": "BOOL", "usage": "Output", "required": True, "visible": True, "default": "0", "description": "Stop command to VFD:O.Stop"},
        {"name": "Drive_Freq_Cmd", "type": "INT", "usage": "Output", "required": True, "visible": True, "default": "0", "description": "Frequency command to VFD:O.FreqCommand (0.01 Hz units)"},
        {"name": "Running_Status", "type": "BOOL", "usage": "Output", "required": True, "visible": True, "default": "0", "description": "Motor Running State"}
    ]

    local_tags = [
        {"name": "Clamped_Speed_Hz", "type": "REAL", "default": "0.0", "description": "Internal Clamped Frequency"}
    ]

    # Ladder logic rungs using modern IEC mnemonics (or legacy, which will auto-modernize)
    rungs = [
        # Rung 0: Run Latch
        "XIC(E_Stop_OK)[XIC(Start_PB) ,XIC(Running_Status) ]XIO(Stop_PB)OTE(Running_Status);",
        # Rung 1: Start/Stop Output Coils
        "[XIC(Running_Status) OTE(Drive_Start_Out) ,XIO(Running_Status) OTE(Drive_Stop_Out) ];",
        # Rung 2: Speed Clamping Lower Limit (Uses modern LT)
        "MOVE(Speed_SP_Hz,Clamped_Speed_Hz);",
        "LT(Clamped_Speed_Hz,Min_Speed_Hz)MOVE(Min_Speed_Hz,Clamped_Speed_Hz);",
        # Rung 3: Speed Clamping Upper Limit (Uses modern GT)
        "GT(Clamped_Speed_Hz,Max_Speed_Hz)MOVE(Max_Speed_Hz,Clamped_Speed_Hz);",
        # Rung 4: Output Frequency Calculation
        "[XIC(Running_Status) CPT(Drive_Freq_Cmd,Clamped_Speed_Hz*100) ,XIO(Running_Status) MOVE(0,Drive_Freq_Cmd) ];"
    ]

    comments = [
        "Rung 0: Start/Stop Motor Latch with E-Stop Permissive",
        "Rung 1: Drive Physical Start and Stop Coils",
        "Rung 2: Initialize Speed and Clamp to Minimum Frequency Limit",
        "Rung 3: Clamp to Maximum Frequency Limit",
        "Rung 4: Scale 0.01 Hz Speed Reference to PowerFlex Drive"
    ]

    # Build schema-compliant AOI L5X
    xml_content = L5XBuilder.build_aoi_envelope(
        controller_name="CompactLogix_Controller",
        aoi_name="AOI_SAMPLE_VFD",
        description="Sample PowerFlex VFD AOI generated via studio5000-live-mcp",
        parameters=parameters,
        local_tags=local_tags,
        rungs=rungs,
        rung_comments=comments,
        software_revision="38.00"
    )

    out_file = "AOI_SAMPLE_VFD.L5X"
    res = L5XBuilder.save_l5x_file(out_file, xml_content)
    print(f"Successfully generated: {res['file_path']}")
    print(f"Total rungs: {res['rungs_validated']}")
    print(f"Bytes written: {res['bytes_written']}")

    # Clean up test output
    if os.path.exists(out_file):
        os.remove(out_file)
        print("Cleaned up temporary export file.")

if __name__ == "__main__":
    main()
