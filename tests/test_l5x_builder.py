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
