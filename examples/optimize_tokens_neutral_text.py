"""
Example: Token Optimization via NeutralText Translation
Demonstrates converting verbose Rockwell XML ladder rungs into compact NeutralText,
saving 85-92% of LLM context window tokens while preserving complete logic semantics.
"""

from studio5000_live_mcp.adapters.logix_offline import LogixOfflineAdapter

SAMPLE_XML_RUNG = """
<RLLContent>
  <Rung Number="0" Type="N">
    <Comment><![CDATA[Tank Low Level Detection: Triggers alarm when level drops below safety threshold.]]></Comment>
    <Text><![CDATA[XIC(Sensor_Healthy)LT(Tank_Level,Low_Level_Limit)TON(Low_Level_Timer,?,?);]]></Text>
  </Rung>
  <Rung Number="1" Type="N">
    <Comment><![CDATA[Feed Pump Permissive: Enables pump run coil when level is above cutoff and no E-Stop.]]></Comment>
    <Text><![CDATA[XIC(E_Stop_OK)XIO(Low_Level_Timer.DN)[XIC(Start_PB) ,XIC(Pump_Running) ]XIO(Stop_PB)OTE(Pump_Running);]]></Text>
  </Rung>
</RLLContent>
"""

def main():
    print("Translating verbose XML rungs to compact Logix NeutralText...")
    adapter = LogixOfflineAdapter()
    result = adapter.translate_to_neutral_text(SAMPLE_XML_RUNG)

    print("\n--- Compact NeutralText Output ---")
    print(result["neutral_text"])
    print("\n--- Token Optimization Metrics ---")
    print(f"Original XML Characters:       {result['metrics']['xml_characters']}")
    print(f"NeutralText Characters:        {result['metrics']['neutral_text_characters']}")
    print(f"Context Reduction:             {result['metrics']['token_reduction_percent']}%")

if __name__ == "__main__":
    main()
