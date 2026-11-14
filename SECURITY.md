# Security & Industrial Safety Policy

## Industrial Controls Safety Boundaries

The **Studio 5000 MCP Server** is designed for integration into manufacturing, process control, and industrial automation environments. As such, software bugs or improper configurations carry physical world consequences.

To safeguard personnel, machinery, and production uptime:

1. **Never Bypass Safety Gates**: The safety checks in `src/studio5000_live_mcp/safety_validator.py` are hardcoded and non-configurable by design. Do not modify or disable these gates.
2. **Key Switch in REM**: When testing live online edits, the controller physical key switch should be in `REM` (Remote Run / Remote Prog). Never attempt unverified edits on machinery actively in production.
3. **Emergency Stop Hardware**: Software controls must **never** replace hardwired or SIL-rated Safety PLC emergency stop circuits.
4. **Test Before Assemble**: Always verify newly injected rungs in `test_edits` mode (Zone `I`/`R`) before permanently committing them with `assemble_edits`.

---

## Reporting Vulnerabilities

If you discover a security vulnerability or a safety bypass in this repository:

1. **Do NOT open a public GitHub issue.**
2. Send a detailed report directly to the repository maintainer via GitHub Private Security Advisories or email.
3. Include:
   - Detailed description of the issue or bypass mechanism.
   - Steps to reproduce the issue.
   - Affected controller models, firmware revisions, and software versions.
   - Proposed remediation, if known.

We will review your submission promptly and coordinate a patch and advisory.
