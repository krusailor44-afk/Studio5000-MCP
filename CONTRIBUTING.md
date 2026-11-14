# Contributing to Studio5000-MCP Server

Thank you for your interest in contributing to **Studio5000-MCP Server**!

This project bridges generative AI models (Claude, Cursor, Antigravity, ChatGPT) with Rockwell Automation Allen-Bradley ControlLogix & CompactLogix PLCs via the official Rockwell Logix Designer Python SDK and offline L5X toolchains.

Because this codebase interacts directly with industrial machinery and live PLC scan cycles, **we hold safety and code quality to the highest possible standard**.

---

## Industrial Safety First

Before submitting any Pull Request, verify that your changes uphold our hardcoded industrial safety gates:

1. **Safety Instrumented Tags**: Edits to tags prefixed with `Safety_` must remain strictly blocked.
2. **Alias and Consumed Tags**: Writing to alias tags or consumed tags must remain strictly denied.
3. **Routine Types**: Online editing is restricted to Relay Ladder Logic (`RLL`). Function Block Diagrams (`FBD`) and Sequential Function Charts (`SFC`) must remain blocked for online write operations.
4. **Human-in-the-Loop Safeguard**: Any commit to non-volatile controller memory (`assemble_edits`) must strictly require explicit manual confirmation (`confirmed=True`).
5. **Rockwell Schema Compliance**: Any generated `.L5X` file must strictly enforce `Use="Target"`, `ContainsContext="true"`, and correct branch bracket structure (`legs >= 2` separated by commas).

---

## Development Setup

### 1. Prerequisites
- Windows 10 / 11 / Server 2022
- Python 3.12+ (64-bit)
- Git

### 2. Clone and Configure Environment
```powershell
git clone https://github.com/krusailor44-afk/Studio5000-MCP.git
cd Studio5000-MCP

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install runtime dependencies and test tools
pip install -r requirements.txt
pip install pytest pytest-asyncio
```

### 3. Run Tests
Every pull request must pass 100% of the unit test suite:
```powershell
pytest tests/ -v
```

---

## Pull Request Guidelines

1. **Branch Naming**:
   - `feature/your-feature-name`
   - `fix/your-bug-fix`
   - `docs/documentation-update`
2. **Commit Messages**: Follow conventional commits:
   - `feat: add support for PowerFlex 755 drive parameters`
   - `fix: resolve nested branch validation on multi-leg rungs`
   - `docs: update Claude Desktop configuration instructions`
3. **Testing**: Add unit tests for any new adapter, tool, or validation rule under `tests/`.
4. **No Controller Required for Offline Tests**: All offline adapter and schema validation tests run completely independently of physical PLC hardware or SDK installation.

---

## Code of Conduct

Please treat all community members with respect, patience, and professional courtesy. We welcome feedback from both software engineers and field industrial controls engineers!
