"""
Unit tests for LogixOfflineAdapter and NeutralText Translation.
"""

import os
import pytest
from studio5000_live_mcp.adapters.logix_offline import LogixOfflineAdapter
from studio5000_live_mcp.adapters.base import UnsupportedOperationError, PLCAdapterError
from studio5000_live_mcp.l5x_builder import L5XValidationError


SAMPLE_L5X = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="38.00" TargetName="SampleSkid" TargetType="Controller" ContainsContext="true">
  <Controller Name="SampleSkid" ProcessorType="5069-L310ER">
    <DataTypes>
      <DataType Name="VFD_STATUS" Description="Drive status structure">
        <Members>
          <Member Name="Running" DataType="BOOL" Dimension="0" Radix="Decimal"/>
          <Member Name="Faulted" DataType="BOOL" Dimension="0" Radix="Decimal"/>
          <Member Name="ActualHz" DataType="REAL" Dimension="0" Radix="Float"/>
        </Members>
      </DataType>
    </DataTypes>
    <Tags>
      <Tag Name="Master_Auto_PB" TagType="Base" DataType="BOOL" ExternalAccess="Read/Write">
        <Description><![CDATA[Master auto start pushbutton]]></Description>
        <DataValue DataType="BOOL" Value="0"/>
      </Tag>
      <Tag Name="Mixer_Drive_Status" TagType="Base" DataType="VFD_STATUS" ExternalAccess="Read/Write"/>
    </Tags>
    <Programs>
      <Program Name="Mixing_Program" Type="Normal" MainRoutineName="MainRoutine">
        <Routines>
          <Routine Name="MainRoutine" Type="RLL">
            <RLLContent>
              <Rung Number="0" Type="N">
                <Comment><![CDATA[Main Start Latch]]></Comment>
                <Text><![CDATA[XIC(Master_Auto_PB) [XIC(Run_Latch) ,XIO(Fault)] OTE(Run_Latch);]]></Text>
              </Rung>
              <Rung Number="1" Type="N">
                <Comment><![CDATA[Speed Command Scaling]]></Comment>
                <Text><![CDATA[[XIO(Auto_Mode) CPT(Speed_Cmd,Speed_SP*60) ,XIC(Auto_Mode) CPT(Speed_Cmd,Man_SP*60) ];]]></Text>
              </Rung>
            </RLLContent>
          </Routine>
        </Routines>
      </Program>
    </Programs>
    <Modules>
      <Module Name="LocalIO" CatalogNumber="5069-IB16" Slot="1" ParentModule="SampleSkid"/>
    </Modules>
  </Controller>
</RSLogix5000Content>
"""


@pytest.fixture
def sample_l5x_file(tmp_path):
    f_path = str(tmp_path / "SampleProject.L5X")
    with open(f_path, "w", encoding="utf-8") as f:
        f.write(SAMPLE_L5X)
    return f_path


def test_offline_parse_l5x(sample_l5x_file):
    adapter = LogixOfflineAdapter(sample_l5x_file)
    res = adapter.parse_l5x()

    assert res["status"] == "success"
    assert res["controller_name"] == "SampleSkid"
    assert res["processor_type"] == "5069-L310ER"
    assert res["software_revision"] == "38.00"
    
    # UDTs
    assert res["udt_count"] == 1
    assert res["udts"][0]["name"] == "VFD_STATUS"
    assert len(res["udts"][0]["members"]) == 3

    # Tags
    assert res["controller_tag_count"] >= 1
    tag_names = [t["name"] for t in res["controller_tags"]]
    assert "Master_Auto_PB" in tag_names

    # Programs & Routines
    assert res["program_count"] == 1
    assert res["programs"][0]["name"] == "Mixing_Program"
    assert res["programs"][0]["routines"][0]["name"] == "MainRoutine"
    assert res["programs"][0]["routines"][0]["rung_count"] == 2

    # Modules
    assert res["module_count"] == 1
    assert res["modules"][0]["catalog_number"] == "5069-IB16"


def test_translate_to_neutral_text(sample_l5x_file):
    adapter = LogixOfflineAdapter()
    res = adapter.translate_to_neutral_text(sample_l5x_file)

    assert res["status"] == "success"
    assert res["rung_count"] == 2
    neutral_text = res["neutral_text"]
    
    # Assert compact neutral text formatting
    assert "Rung 0: XIC(Master_Auto_PB)" in neutral_text
    assert "Rung 1: [XIO(Auto_Mode)" in neutral_text
    assert "Main Start Latch" in neutral_text
    
    # Token optimization metrics
    metrics = res["metrics"]
    assert metrics["xml_characters"] > metrics["neutral_text_characters"]
    assert metrics["token_reduction_percent"] > 60.0


def test_generate_l5x_routine_import(tmp_path):
    adapter = LogixOfflineAdapter()
    out_file = str(tmp_path / "ImportRoutine.L5X")
    rungs = [
        "XIC(Start_PB) [XIC(Run_Latch) ,XIO(Stop_PB)] OTE(Run_Latch);",
        "[XIO(Mode) MOV(10, Speed) ,XIC(Mode) MOV(20, Speed) ];"
    ]
    comments = ["Run latching", "Speed preset"]

    res = adapter.generate_l5x_import(
        target_type="Routine",
        target_name="PumpControl",
        program_name="Mixing_Program",
        controller_name="SampleSkid",
        rungs=rungs,
        rung_comments=comments,
        output_path=out_file
    )

    assert res["status"] == "success"
    assert res["target_type"] == "Routine"
    assert os.path.exists(out_file)

    # Verify generated file contains target elements
    with open(out_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert 'Use="Target" Name="PumpControl"' in content
    assert 'ContainsContext="true"' in content


def test_generate_l5x_rejects_malformed_branch():
    """Confirms Error 12740-0 prevention in offline code generation."""
    adapter = LogixOfflineAdapter()
    bad_rungs = ["[[XIC(InA) OTE(OutB) ]];"]

    with pytest.raises(L5XValidationError) as exc_info:
        adapter.generate_l5x_import(
            target_type="Routine",
            target_name="BadRoutine",
            rungs=bad_rungs
        )
    assert "12740-0" in str(exc_info.value)


def test_offline_read_routine(sample_l5x_file):
    adapter = LogixOfflineAdapter(sample_l5x_file)
    res = adapter.read_routine("Mixing_Program", "MainRoutine")

    assert res["routine"] == "MainRoutine"
    assert res["rung_count"] == 2
    assert "XIC(Master_Auto_PB)" in res["rungs"][0]["logic"]
    assert res["rungs"][0]["comment"] == "Main Start Latch"


def test_offline_read_tag(sample_l5x_file):
    adapter = LogixOfflineAdapter(sample_l5x_file)
    res = adapter.read_tag("Master_Auto_PB")

    assert res["tag"] == "Master_Auto_PB"
    assert res["data_type"] == "BOOL"
    assert res["initial_value"] == "0"


def test_offline_adapter_rejects_online_operations():
    adapter = LogixOfflineAdapter()
    
    with pytest.raises(UnsupportedOperationError) as exc_info:
        adapter.propose_edit("MainProg", "MainRoutine", 0, 0, ["NOP;"])
    assert "propose_edit is an online controller operation" in str(exc_info.value)

    with pytest.raises(UnsupportedOperationError) as exc_info:
        adapter.test_edits("MainProg", "MainRoutine")
    assert "test_edits requires an active online controller connection" in str(exc_info.value)

    with pytest.raises(UnsupportedOperationError) as exc_info:
        adapter.assemble_edits("MainProg", "MainRoutine", confirmed=True)
    assert "assemble_edits permanently commits pending edits" in str(exc_info.value)
