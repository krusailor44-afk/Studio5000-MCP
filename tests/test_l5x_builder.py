"""
Unit tests for Rockwell Studio 5000 L5X Builder and Validator.

Verifies:
1. Routine Partial Import envelope formatting.
2. AOI Definition envelope formatting with exact Rockwell schema requirements.
3. Catching missing Use="Target" (Rockwell Error 25134-80044178 prevention).
4. Catching target name mismatches.
5. Server tool invocations (validate_l5x_file and build_aoi_l5x).
"""

import os
import pytest
from studio5000_live_mcp.l5x_builder import L5XBuilder, L5XValidationError
from studio5000_live_mcp.server import validate_l5x_file, build_aoi_l5x


def test_build_routine_envelope():
    xml = L5XBuilder.build_partial_import_envelope(
        controller_name="TestCPU",
        program_name="MainProgram",
        routine_name="TestRoutine",
        rungs=["XIC(Start) OTE(Run);"],
        rung_comments=["Run logic"],
        software_revision="38.00"
    )
    assert '<RSLogix5000Content' in xml
    assert 'TargetType="Routine"' in xml
    assert 'ContainsContext="true"' in xml
    assert '<Routine Use="Target" Name="TestRoutine" Type="RLL">' in xml
    assert 'XIC(Start) OTE(Run);' in xml

    res = L5XBuilder.validate_l5x(xml)
    assert res["valid"] is True
    assert res["target_type"] == "Routine"
    assert res["target_name"] == "TestRoutine"


def test_build_aoi_envelope_success():
    params = [
        {"name": "Cmd_Start", "type": "BOOL", "usage": "Input", "description": "Start command"},
        {"name": "Status_Run", "type": "BOOL", "usage": "Output", "description": "Running status"}
    ]
    local_tags = [
        {"name": "Run_Timer", "type": "TIMER", "description": "Internal run timer"}
    ]
    rungs = [
        "XIC(Cmd_Start) OTE(Status_Run);"
    ]

    xml = L5XBuilder.build_aoi_envelope(
        controller_name="TestCPU",
        aoi_name="AOI_PUMP",
        description="Pump control block",
        parameters=params,
        local_tags=local_tags,
        rungs=rungs,
        software_revision="38.00"
    )

    assert '<RSLogix5000Content' in xml
    assert 'TargetType="AddOnInstructionDefinition"' in xml
    assert 'ContainsContext="true"' in xml
    assert '<AddOnInstructionDefinitions Use="Context">' in xml
    assert '<AddOnInstructionDefinition Use="Target" Name="AOI_PUMP"' in xml
    assert '<Parameter Name="EnableIn"' in xml
    assert '<Parameter Name="EnableOut"' in xml
    assert '<Structure DataType="TIMER">' in xml

    res = L5XBuilder.validate_l5x(xml)
    assert res["valid"] is True
    assert res["target_type"] == "AddOnInstructionDefinition"
    assert res["target_name"] == "AOI_PUMP"


def test_validator_detects_missing_use_target():
    """Verifies prevention of Rockwell Error 25134-80044178."""
    bad_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="38.00" TargetName="AOI_TEST" TargetType="AddOnInstructionDefinition" ContainsContext="true">
  <Controller Use="Context" Name="TestCPU">
    <AddOnInstructionDefinitions Use="Context">
      <AddOnInstructionDefinition Name="AOI_TEST">
        <Parameters></Parameters>
      </AddOnInstructionDefinition>
    </AddOnInstructionDefinitions>
  </Controller>
</RSLogix5000Content>
"""
    with pytest.raises(L5XValidationError) as exc_info:
        L5XBuilder.validate_l5x(bad_xml)

    assert "25134-80044178" in str(exc_info.value)
    assert "Use='Target'" in str(exc_info.value)


def test_validator_detects_target_name_mismatch():
    bad_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="38.00" TargetName="EXPECTED_NAME" TargetType="Routine" ContainsContext="true">
  <Controller Use="Context" Name="TestCPU">
    <Programs Use="Context">
      <Program Use="Context" Name="Main">
        <Routines Use="Context">
          <Routine Use="Target" Name="DIFFERENT_NAME" Type="RLL">
          </Routine>
        </Routines>
      </Program>
    </Programs>
  </Controller>
</RSLogix5000Content>
"""
    with pytest.raises(L5XValidationError) as exc_info:
        L5XBuilder.validate_l5x(bad_xml)

    assert "TargetName mismatch" in str(exc_info.value)


def test_server_build_and_validate_tools(tmp_path):
    out_file = str(tmp_path / "TEST_AOI.L5X")
    build_res = build_aoi_l5x(
        controller_name="SpectrumBrands_CPU",
        aoi_name="TEST_AOI",
        description="Automated unit test AOI",
        parameters=[{"name": "InVal", "type": "REAL", "usage": "Input"}],
        rungs=["MOVE(InVal, InVal);"],
        output_path=out_file
    )

    assert build_res["status"] == "success"
    assert os.path.exists(out_file)

    val_res = validate_l5x_file(out_file)
    assert val_res["valid"] is True
    assert val_res["target_name"] == "TEST_AOI"
    assert val_res["target_type"] == "AddOnInstructionDefinition"
    assert val_res.get("rungs_validated") == 1


def test_validate_rll_syntax_detects_single_leg_branch():
    """Verifies prevention of Studio 5000 Error 12740-0 (Line 162 single-leg branch)."""
    # The exact malformed rung that caused Error 12740-0 in Studio 5000
    bad_rung = "[[XIO(Auto_Man_Mode) CPT(Drive_Freq_Cmd,Auto_SP_Percent/100.0*Max_Freq_Hz*100) ,XIC(Auto_Man_Mode) CPT(Drive_Freq_Cmd,Man_SP_Percent/100.0*Max_Freq_Hz*100) ] ];"
    with pytest.raises(L5XValidationError) as exc_info:
        L5XBuilder.validate_rll_syntax(bad_rung, rung_idx=3)

    assert "Rung 3" in str(exc_info.value)
    assert "Invalid parallel branch" in str(exc_info.value)
    assert "12740-0" in str(exc_info.value)

    # Bare single-leg branch
    with pytest.raises(L5XValidationError) as exc_info:
        L5XBuilder.validate_rll_syntax("[XIC(Start_PB) OTE(Run_Motor) ];")
    assert "branch has only 1 leg" in str(exc_info.value)


def test_validate_rll_syntax_detects_unclosed_brackets_and_parens():
    with pytest.raises(L5XValidationError) as exc_info:
        L5XBuilder.validate_rll_syntax("XIC(Start_PB OTE(Run_Motor);")
    assert "Unbalanced opening parenthesis" in str(exc_info.value)

    with pytest.raises(L5XValidationError) as exc_info:
        L5XBuilder.validate_rll_syntax("[XIC(Start) ,XIC(Run) OTE(Motor);")
    assert "Unclosed branch" in str(exc_info.value)


def test_validate_rll_syntax_detects_empty_legs():
    with pytest.raises(L5XValidationError) as exc_info:
        L5XBuilder.validate_rll_syntax("[, XIC(Start) ] OTE(Motor);")
    assert "Empty branch leg" in str(exc_info.value)

    with pytest.raises(L5XValidationError) as exc_info:
        L5XBuilder.validate_rll_syntax("[XIC(Start) , ] OTE(Motor);")
    assert "Empty branch leg" in str(exc_info.value)


def test_validate_rll_syntax_detects_missing_semicolon():
    with pytest.raises(L5XValidationError) as exc_info:
        L5XBuilder.validate_rll_syntax("XIC(Start) OTE(Motor)")
    assert "must terminate with a semicolon" in str(exc_info.value)


def test_validate_rll_syntax_accepts_valid_branches_and_array_tags():
    # Valid 2-leg branch
    L5XBuilder.validate_rll_syntax("[XIC(Auto) OTE(Cmd1) ,XIC(Man) OTE(Cmd2) ];")

    # Valid nested branches
    L5XBuilder.validate_rll_syntax("[[XIO(Mode) XIC(Start) ,XIC(Mode) XIC(Run) ] OTE(Active) ,XIC(Active) OTE(Out1) ];")

    # Array index tags inside parens
    L5XBuilder.validate_rll_syntax("XIC(FAULT[0].11) [XIC(Remote_ENBT[1]) ,XIC(Local:1:I.Data[2]) ] OTE(Alarm[0]);")

    # Complex CPT expression
    L5XBuilder.validate_rll_syntax("CPT(WATER_VFD_P1:O.FreqCommand,(PID_FOR_P1_CV/16383*6000));")


def test_build_aoi_envelope_rejects_invalid_rung():
    params = [{"name": "InVal", "type": "REAL", "usage": "Input"}]
    bad_rungs = ["[[XIC(InVal) OTE(OutVal) ]];"]

    with pytest.raises(L5XValidationError) as exc_info:
        L5XBuilder.build_aoi_envelope(
            controller_name="TestCPU",
            aoi_name="AOI_TEST",
            parameters=params,
            rungs=bad_rungs
        )
    assert "12740-0" in str(exc_info.value)


def test_modernize_rll_mnemonics_iec_conversion():
    """Verifies that legacy Rockwell comparison mnemonics are modernized for v36+."""
    legacy_rung = "LES(Target, Min) GRT(Target, Max) LEQ(A, B) GEQ(C, D) EQU(Mode, 1) NEQ(State, 0) OTE(Valid);"
    modernized = L5XBuilder.modernize_rll_mnemonics(legacy_rung, software_revision="38.00")
    assert "LT(Target, Min)" in modernized
    assert "GT(Target, Max)" in modernized
    assert "LE(A, B)" in modernized
    assert "GE(C, D)" in modernized
    assert "EQ(Mode, 1)" in modernized
    assert "NE(State, 0)" in modernized
    assert "LES(" not in modernized
    assert "GRT(" not in modernized

    # On v32 (pre-v36), legacy mnemonics must be preserved
    pre_v36 = L5XBuilder.modernize_rll_mnemonics(legacy_rung, software_revision="32.00")
    assert pre_v36 == legacy_rung


def test_build_aoi_envelope_auto_modernizes_for_v38():
    """Verifies that building an AOI automatically converts legacy mnemonics for v38 target."""
    xml = L5XBuilder.build_aoi_envelope(
        controller_name="SpectrumBrands_CPU",
        aoi_name="AOI_TEST_MODERN",
        rungs=["LES(Val, 10) MOVE(10, Val);"],
        software_revision="38.03"
    )
    assert "LT(Val, 10)" in xml
    assert "LES(" not in xml

    val = L5XBuilder.validate_l5x(xml)
    assert val["valid"] is True
    assert len(val.get("warnings", [])) == 0


def test_validate_l5x_warns_on_legacy_mnemonics():
    """Verifies that validate_l5x flags legacy mnemonics in v38 documents as actionable warnings."""
    raw_v38_with_legacy = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="38.00" TargetName="TestRoutine" TargetType="Routine" ContainsContext="true">
  <Controller Use="Context" Name="TestCPU">
    <Programs Use="Context">
      <Program Use="Context" Name="Main">
        <Routines Use="Context">
          <Routine Use="Target" Name="TestRoutine" Type="RLL">
            <RLLContent>
              <Rung Number="0" Type="N">
                <Text><![CDATA[LES(Speed, 10) OTE(Slow);]]></Text>
              </Rung>
            </RLLContent>
          </Routine>
        </Routines>
      </Program>
    </Programs>
  </Controller>
</RSLogix5000Content>
"""
    val = L5XBuilder.validate_l5x(raw_v38_with_legacy)
    assert val["valid"] is True
    assert len(val["warnings"]) == 1
    assert "Uses legacy comparison mnemonic 'LES'" in val["warnings"][0]
    assert "Studio 5000 v36+ requires modern IEC mnemonic 'LT'" in val["warnings"][0]


