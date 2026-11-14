"""
Unit Tests for Studio 5000 Live MCP Server Safety Gates.
"""

import pytest
from studio5000_live_mcp.safety_validator import SafetyValidator, SafetyGateViolation
from studio5000_live_mcp.server import assemble_edits


def test_safety_tag_prefix_rejection():
    """Verify that tags with 'Safety_' prefix in any casing are rejected."""
    with pytest.raises(SafetyGateViolation) as exc_info:
        SafetyValidator.validate_tag_name("Safety_Estop_PB")
    assert "PROHIBITED_SAFETY_TAG" in str(exc_info.value)

    with pytest.raises(SafetyGateViolation) as exc_info:
        SafetyValidator.validate_tag_name("safety_light_curtain")
    assert "PROHIBITED_SAFETY_TAG" in str(exc_info.value)

    with pytest.raises(SafetyGateViolation) as exc_info:
        SafetyValidator.validate_tag_name("SAFETY_DOOR_INTERLOCK")
    assert "PROHIBITED_SAFETY_TAG" in str(exc_info.value)

    # Valid non-safety tags must pass
    SafetyValidator.validate_tag_name("Standard_Pump_Run")
    SafetyValidator.validate_tag_name("Mixer_Motor_Speed")


def test_alias_tag_rejection():
    """Verify that alias tags are rejected."""
    metadata = {
        "DataType": "BOOL",
        "is_alias": True,
        "alias_for": "Local:1:I.Data.0"
    }
    with pytest.raises(SafetyGateViolation) as exc_info:
        SafetyValidator.validate_tag_metadata("Start_Button_Alias", metadata)
    assert "PROHIBITED_ALIAS_TAG" in str(exc_info.value)


def test_consumed_tag_rejection():
    """Verify that consumed tags are rejected."""
    metadata = {
        "DataType": "DINT",
        "Usage": "Consumed"
    }
    with pytest.raises(SafetyGateViolation) as exc_info:
        SafetyValidator.validate_tag_metadata("Interlock_In_From_PLC2", metadata)
    assert "PROHIBITED_CONSUMED_TAG" in str(exc_info.value)


def test_external_access_none_rejection():
    """Verify that tags with ExternalAccess = None are rejected."""
    metadata = {
        "DataType": "REAL",
        "ExternalAccess": "None"
    }
    with pytest.raises(SafetyGateViolation) as exc_info:
        SafetyValidator.validate_tag_metadata("Internal_PID_Gain", metadata)
    assert "PROHIBITED_EXTERNAL_ACCESS_NONE" in str(exc_info.value)


def test_unsupported_routine_types():
    """Verify that FBD, SFC, and ST routines are rejected for online edits."""
    with pytest.raises(SafetyGateViolation) as exc_info:
        SafetyValidator.validate_routine_type("Process_Control", "FBD")
    assert "UNSUPPORTED_ROUTINE_TYPE" in str(exc_info.value)

    with pytest.raises(SafetyGateViolation) as exc_info:
        SafetyValidator.validate_routine_type("Batch_Sequence", "SFC")
    assert "UNSUPPORTED_ROUTINE_TYPE" in str(exc_info.value)

    # RLL ladder logic must pass
    SafetyValidator.validate_routine_type("MainRoutine", "RLL")


def test_aoi_instruction_rejection():
    """Verify that Add-On Instructions (AOIs) are caught and rejected in proposed rungs."""
    known_aois = {"VFD_CONTROL", "VALVE_AOI"}
    
    # Rung calling an AOI
    bad_rung = ["XIC(Auto_Mode)VFD_CONTROL(VFD_Drive_1)OTE(Drive_Ready);"]
    with pytest.raises(SafetyGateViolation) as exc_info:
        SafetyValidator.validate_proposed_rungs(
            routine_name="MotorControl",
            routine_type="RLL",
            rungs=bad_rung,
            known_aois=known_aois
        )
    assert "PROHIBITED_AOI_INSTRUCTION" in str(exc_info.value)


def test_valid_rll_rung_acceptance():
    """Verify that standard ladder logic instructions and standard tags pass validation."""
    valid_rungs = [
        "XIC(Start_PB)XIO(Stop_PB)OTE(Motor_Run);",
        "TON(Mixer_Timer,?,?);",
        "EQU(State_Step,10)MOV(50,Pump_Speed);"
    ]
    SafetyValidator.validate_proposed_rungs(
        routine_name="MainRoutine",
        routine_type="RLL",
        rungs=valid_rungs
    )


def test_iec_comparison_instructions_accepted():
    """Verify that Studio 5000 v36+ IEC comparisons (EQ, NE, LT, LE, GT, GE) are accepted."""
    iec_rungs = [
        "LT(Target_Speed_Hz,Min_Speed_Hz)MOVE(Min_Speed_Hz,Target_Speed_Hz);",
        "GT(Target_Speed_Hz,Max_Speed_Hz)MOVE(Max_Speed_Hz,Target_Speed_Hz);",
        "EQ(Port_Process_Data_Size,0)MOVE(1,Data_Size);",
        "LE(Level_PV,Low_Limit)OTE(Low_Alarm);",
        "GE(Level_PV,High_Limit)OTE(High_Alarm);",
        "NE(Recipe_ID,0)OTE(Recipe_Active);"
    ]
    SafetyValidator.validate_proposed_rungs(
        routine_name="MainRoutine",
        routine_type="RLL",
        rungs=iec_rungs
    )


def test_assemble_edits_unconfirmed_safeguard():
    """Verify that assemble_edits refuses execution when confirmed=False."""
    result = assemble_edits(program_name="MainProgram", routine_name="MainRoutine", confirmed=False)
    assert result["status"] == "REJECTED_BY_SAFEGUARD"
    assert "HUMAN-IN-THE-LOOP SAFEGUARD TRIGGERED" in result["error"]
    assert result["confirmed"] is False


def test_cpt_and_math_instructions_accepted():
    """Verify that CPT, PID, MOVE, and standard math instructions pass without AOI false-positives."""
    rungs = [
        "CPT(Drive_Freq_Cmd,(Auto_SP_Percent/100)*(Max_Freq_Hz*100));",
        "MOVE(100, Preset_Value);",
        "PID(Process_PID, Process_PV, 0, Process_CV, 0, 0, 0);"
    ]
    SafetyValidator.validate_proposed_rungs(
        routine_name="MainRoutine",
        routine_type="RLL",
        rungs=rungs
    )


def test_cpt_expression_detects_safety_tags():
    """Verify that safety tags embedded inside complex CPT expressions are caught and rejected."""
    bad_cpt_rung = ["CPT(Target_Speed, (Safety_Speed_Limit / 100) * 6000);"]
    with pytest.raises(SafetyGateViolation) as exc_info:
        SafetyValidator.validate_proposed_rungs(
            routine_name="MainRoutine",
            routine_type="RLL",
            rungs=bad_cpt_rung
        )
    assert "PROHIBITED_SAFETY_TAG" in str(exc_info.value)
    assert "Safety_Speed_Limit" in str(exc_info.value)

