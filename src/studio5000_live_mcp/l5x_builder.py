"""
L5X XML Fragment Builder for Studio 5000 Partial Imports.

Constructs compliant Rockwell Partial Import L5X XML documents matching the schema
expected by LogixProject.partial_import_rungs_from_xml_file().
"""

from typing import List, Dict, Optional, Any
from xml.sax.saxutils import escape


class L5XBuilder:
    """Builds Rockwell Logix XML Partial Import envelopes."""

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

        # Full L5X Envelope
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
