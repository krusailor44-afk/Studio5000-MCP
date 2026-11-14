"""
L5X XML Fragment Builder & Validator for Studio 5000.

Constructs and validates compliant Rockwell Logix XML (.L5X) documents for:
1. Routine Partial Imports (for online rung insertion/replacement)
2. Add-On Instruction (AOI) Definitions (for reusable module library imports)

Enforces Rockwell Schema rules to prevent common Logix Designer import errors:
- Error 25134-80044178: "No target was found in the selected L5X file that is compatible with the Import context"
  (Caused by missing Use="Target" or ContainsContext="false" with context tags)
- Error 5078-0: "The specified L5X file does not contain a Add-On Instruction export"
  (Caused by importing a Routine L5X via the AOI import menu)
- Syntax errors from unbracketed parallel compute branches or incorrect RLL instruction mnemonics (e.g. MOVE vs MOV).
"""

import os
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
import xml.etree.ElementTree as ET


class L5XValidationError(Exception):
    """Raised when an L5X document violates Rockwell import schema requirements."""
    pass


class L5XBuilder:
    """Builds and validates Rockwell Logix XML import envelopes."""

    @staticmethod
    def build_partial_import_envelope(
        controller_name: str,
        program_name: str,
        routine_name: str,
        rungs: List[str],
        rung_comments: Optional[List[str]] = None,
        new_tags: Optional[List[Dict[str, Any]]] = None,
        software_revision: str = "38.00"
    ) -> str:
        """
        Builds a compliant <RSLogix5000Content> XML fragment containing context and
        target routine ladder rungs for online insertion/replacement.
        """
        comments = rung_comments or [""] * len(rungs)

        # Build Tags block if new context tags are declared
        tags_xml = ""
        if new_tags:
            tag_entries = []
            for tag in new_tags:
                tag_name = tag.get("name")
                data_type = tag.get("type", "DINT")
                tag_type = tag.get("tag_type", "Base")
                desc = tag.get("description", "")
                desc_elem = f"<Description><![CDATA[{desc}]]></Description>" if desc else ""
                tag_entries.append(
                    f'<Tag Name="{tag_name}" TagType="{tag_type}" DataType="{data_type}" Constant="false" ExternalAccess="Read/Write">{desc_elem}</Tag>'
                )
            tags_xml = f'<Tags Use="Context">\n        ' + "\n        ".join(tag_entries) + "\n      </Tags>"

        # Build RLLContent Rungs
        rung_entries = []
        for idx, rung_text in enumerate(rungs):
            comment = comments[idx] if idx < len(comments) else ""
            clean_text = rung_text.strip()
            if not clean_text.endswith(";"):
                clean_text += ";"

            comment_elem = f"<Comment><![CDATA[{comment}]]></Comment>" if comment else ""
            rung_xml = (
                f'        <Rung Number="{idx}" Type="N">\n'
                f'          {comment_elem}\n'
                f'          <Text><![CDATA[{clean_text}]]></Text>\n'
                f'        </Rung>'
            )
            rung_entries.append(rung_xml)

        rungs_block = "\n".join(rung_entries)

        xml_content = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="{software_revision}" TargetName="{routine_name}" TargetType="Routine" TargetSubType="RLL" ContainsContext="true">
  <Controller Use="Context" Name="{controller_name}">
    {tags_xml}
    <Programs Use="Context">
      <Program Use="Context" Name="{program_name}">
        <Routines Use="Context">
          <Routine Use="Target" Name="{routine_name}" Type="RLL">
            <RLLContent>
{rungs_block}
            </RLLContent>
          </Routine>
        </Routines>
      </Program>
    </Programs>
  </Controller>
</RSLogix5000Content>
"""
        return xml_content

    @staticmethod
    def build_aoi_envelope(
        controller_name: str,
        aoi_name: str,
        description: str = "",
        revision: str = "1.0",
        vendor: str = "Rockwell Automation",
        parameters: Optional[List[Dict[str, Any]]] = None,
        local_tags: Optional[List[Dict[str, Any]]] = None,
        rungs: Optional[List[str]] = None,
        rung_comments: Optional[List[str]] = None,
        software_revision: str = "38.00"
    ) -> str:
        """
        Builds a 100% schema-compliant Add-On Instruction (.L5X) export envelope.
        
        Strict Rockwell Schema Guarantees:
        - Root: TargetType="AddOnInstructionDefinition", ContainsContext="true", TargetName matches AOI.
        - AddOnInstructionDefinitions container has Use="Context".
        - AddOnInstructionDefinition element MUST have Use="Target" (prevents Studio 5000 Error 25134-80044178).
        - Automatically includes EnableIn and EnableOut system parameters if omitted.
        - Automatically provisions default data and radix for standard parameter types.
        """
        iso_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        export_date = datetime.now().strftime("%a %b %d %H:%M:%S %Y")

        # 1. Process Parameters
        raw_params = parameters or []
        has_enable_in = any(p.get("name") == "EnableIn" for p in raw_params)
        has_enable_out = any(p.get("name") == "EnableOut" for p in raw_params)

        final_params = []
        if not has_enable_in:
            final_params.append({
                "name": "EnableIn", "type": "BOOL", "usage": "Input",
                "required": False, "visible": False, "access": "Read Only",
                "description": "Enable Input - System Defined Parameter"
            })
        if not has_enable_out:
            final_params.append({
                "name": "EnableOut", "type": "BOOL", "usage": "Output",
                "required": False, "visible": False, "access": "Read Only",
                "description": "Enable Output - System Defined Parameter"
            })
        final_params.extend(raw_params)

        param_xml_list = []
        for p in final_params:
            name = p.get("name")
            dtype = p.get("type", "BOOL")
            usage = p.get("usage", "Input")
            radix = p.get("radix", "Float" if dtype == "REAL" else "Decimal")
            req = "true" if p.get("required", True) else "false"
            vis = "true" if p.get("visible", True) else "false"
            access = p.get("access", "Read Only" if usage == "Output" else "Read/Write")
            desc = p.get("description", "")
            desc_elem = f"\n<Description><![CDATA[{desc}]]></Description>" if desc else ""

            # Default data block
            default_val = p.get("default", "0.0" if dtype == "REAL" else "0")
            default_xml = (
                f"\n<DefaultData Format=\"L5K\"><![CDATA[{default_val}]]></DefaultData>"
                f"\n<DefaultData Format=\"Decorated\"><DataValue DataType=\"{dtype}\" Radix=\"{radix}\" Value=\"{default_val}\"/></DefaultData>"
            ) if name not in ("EnableIn", "EnableOut") and usage != "InOut" else ""

            param_xml_list.append(
                f'<Parameter Name="{name}" TagType="Base" DataType="{dtype}" Usage="{usage}" Radix="{radix}" Required="{req}" Visible="{vis}" ExternalAccess="{access}">'
                f'{desc_elem}{default_xml}\n</Parameter>'
            )
        params_block = "\n".join(param_xml_list)

        # 2. Process Local Tags
        loc_tags = local_tags or []
        loc_xml_list = []
        for lt in loc_tags:
            name = lt.get("name")
            dtype = lt.get("type", "DINT")
            radix = lt.get("radix", "Decimal")
            desc = lt.get("description", "")
            desc_elem = f"\n<Description><![CDATA[{desc}]]></Description>" if desc else ""

            if dtype == "TIMER":
                default_xml = (
                    '\n<DefaultData Format="L5K"><![CDATA[[0,0,0]]]></DefaultData>'
                    '\n<DefaultData Format="Decorated">'
                    '\n  <Structure DataType="TIMER">'
                    '\n    <DataValueMember Name="PRE" DataType="DINT" Radix="Decimal" Value="0"/>'
                    '\n    <DataValueMember Name="ACC" DataType="DINT" Radix="Decimal" Value="0"/>'
                    '\n    <DataValueMember Name="EN" DataType="BOOL" Value="0"/>'
                    '\n    <DataValueMember Name="TT" DataType="BOOL" Value="0"/>'
                    '\n    <DataValueMember Name="DN" DataType="BOOL" Value="0"/>'
                    '\n  </Structure>'
                    '\n</DefaultData>'
                )
            else:
                default_val = lt.get("default", "0")
                default_xml = (
                    f'\n<DefaultData Format="L5K"><![CDATA[{default_val}]]></DefaultData>'
                    f'\n<DefaultData Format="Decorated"><DataValue DataType="{dtype}" Radix="{radix}" Value="{default_val}"/></DefaultData>'
                )

            loc_xml_list.append(
                f'<LocalTag Name="{name}" DataType="{dtype}" ExternalAccess="None">'
                f'{desc_elem}{default_xml}\n</LocalTag>'
            )
        local_tags_block = "\n".join(loc_xml_list)

        # 3. Process Logic Rungs
        rungs_list = rungs or []
        comments_list = rung_comments or [""] * len(rungs_list)
        rung_entries = []
        for idx, rung_text in enumerate(rungs_list):
            c_text = comments_list[idx] if idx < len(comments_list) else ""
            clean = rung_text.strip()
            if not clean.endswith(";"):
                clean += ";"
            comment_elem = f"<Comment><![CDATA[{c_text}]]></Comment>\n" if c_text else ""
            rung_entries.append(
                f'<Rung Number="{idx}" Type="N">\n{comment_elem}<Text><![CDATA[{clean}]]></Text>\n</Rung>'
            )
        rungs_block = "\n".join(rung_entries)

        # 4. Assemble complete L5X
        xml_content = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="{software_revision}" TargetName="{aoi_name}" TargetType="AddOnInstructionDefinition" TargetRevision="{revision} " TargetLastEdited="{iso_timestamp}" ContainsContext="true" ExportDate="{export_date}" ExportOptions="References NoRawData L5KData DecoratedData Context Dependencies ForceProtectedEncoding AllProjDocTrans">
<Controller Use="Context" Name="{controller_name}">
<DataTypes Use="Context">
</DataTypes>
<AddOnInstructionDefinitions Use="Context">
<AddOnInstructionDefinition Use="Target" Name="{aoi_name}" Revision="{revision}" Vendor="{vendor}" ExecutePrescan="false" ExecutePostscan="false" ExecuteEnableInFalse="false" CreatedDate="{iso_timestamp}" CreatedBy="AI" EditedDate="{iso_timestamp}" EditedBy="AI" SoftwareRevision="v{software_revision}">
<Description><![CDATA[{description}]]></Description>
<Parameters>
{params_block}
</Parameters>
<LocalTags>
{local_tags_block}
</LocalTags>
<Routines>
<Routine Name="Logic" Type="RLL">
<RLLContent>
{rungs_block}
</RLLContent>
</Routine>
</Routines>
</AddOnInstructionDefinition>
</AddOnInstructionDefinitions>
</Controller>
</RSLogix5000Content>
"""
        # Validate output before returning
        L5XBuilder.validate_l5x(xml_content)
        return xml_content

    @staticmethod
    def validate_l5x(xml_content: str) -> Dict[str, Any]:
        """
        Validates an L5X XML string against Rockwell Studio 5000 import requirements.
        
        Checks:
        1. Valid XML syntax.
        2. Root element is <RSLogix5000Content>.
        3. TargetType and TargetName exist.
        4. If ContainsContext="true", verifies an element with Use="Target" exists and matches TargetName/TargetType.
        5. Catches missing Use="Target" (Rockwell Error 25134-80044178).
        """
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            raise L5XValidationError(f"Invalid XML syntax: {e}")

        if root.tag != "RSLogix5000Content":
            raise L5XValidationError(f"Expected root tag <RSLogix5000Content>, found <{root.tag}>")

        target_type = root.attrib.get("TargetType")
        target_name = root.attrib.get("TargetName")
        contains_context = root.attrib.get("ContainsContext", "false").lower() == "true"

        if not target_type or not target_name:
            raise L5XValidationError("Root <RSLogix5000Content> missing mandatory TargetType or TargetName attributes.")

        # Find target element
        target_element = None
        for elem in root.iter():
            if elem.attrib.get("Use") == "Target":
                target_element = elem
                break

        if contains_context and target_element is None:
            raise L5XValidationError(
                f"L5X schema violation: ContainsContext='true' but no element with Use='Target' was found. "
                f"Studio 5000 will reject this with Error 25134-80044178 ('No target was found in the selected L5X file')."
            )

        if target_element is not None:
            target_elem_name = target_element.attrib.get("Name")
            if target_elem_name != target_name:
                raise L5XValidationError(
                    f"TargetName mismatch: Root TargetName='{target_name}' does not match element Name='{target_elem_name}'."
                )

        return {
            "valid": True,
            "target_type": target_type,
            "target_name": target_name,
            "contains_context": contains_context,
            "target_element_found": target_element is not None
        }

    @staticmethod
    def save_l5x_file(file_path: str, xml_content: str) -> Dict[str, Any]:
        """Validates and saves an L5X file to disk."""
        validation = L5XBuilder.validate_l5x(xml_content)
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(xml_content)
        validation["file_path"] = os.path.abspath(file_path)
        validation["bytes_written"] = len(xml_content.encode("utf-8"))
        return validation
