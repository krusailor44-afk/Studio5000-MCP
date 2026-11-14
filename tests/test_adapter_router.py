"""
Unit tests for AdapterRouter and Error Shielding.
"""

import os
import pytest
from studio5000_live_mcp.adapters.router import AdapterRouter
from studio5000_live_mcp.adapters.base import AdapterMode, PLCAdapterError, UnsupportedOperationError
from studio5000_live_mcp.server import shield_mcp_tool, read_routine, assemble_edits


def test_router_state_switching(tmp_path):
    router = AdapterRouter()
    assert router.mode == AdapterMode.UNCONFIGURED

    # 1. Switch to OFFLINE mode with .L5X
    l5x_file = str(tmp_path / "test.L5X")
    with open(l5x_file, "w") as f:
        f.write("<RSLogix5000Content TargetName='Test' TargetType='Controller'/>")

    res_l5x = router.set_active_project(l5x_file)
    assert res_l5x["status"] == "success"
    assert router.mode == AdapterMode.OFFLINE
    assert router.get_adapter() is router.offline_adapter

    # 2. Switch to ONLINE mode with .ACD
    acd_file = str(tmp_path / "test.ACD")
    with open(acd_file, "w") as f:
        f.write("mock binary acd content")

    res_acd = router.set_active_project(acd_file)
    assert res_acd["status"] == "success"
    assert router.mode == AdapterMode.ONLINE
    assert router.get_adapter() is router.online_adapter


def test_router_rejects_invalid_extension(tmp_path):
    router = AdapterRouter()
    txt_file = str(tmp_path / "test.txt")
    with open(txt_file, "w") as f:
        f.write("hello")

    with pytest.raises(PLCAdapterError) as exc_info:
        router.set_active_project(txt_file)
    assert "Unsupported file format" in str(exc_info.value)


def test_router_rejects_missing_file():
    router = AdapterRouter()
    with pytest.raises(PLCAdapterError) as exc_info:
        router.set_active_project("C:\\NonExistent\\Path\\Project.ACD")
    assert "Project file not found" in str(exc_info.value)


def test_shield_mcp_tool_catches_unsupported_operation():
    @shield_mcp_tool
    def failing_tool():
        raise UnsupportedOperationError("Test offline rejection")

    res = failing_tool()
    assert res["status"] == "UNSUPPORTED_OPERATION"
    assert "Test offline rejection" in res["error"]


def test_shield_mcp_tool_catches_unexpected_exception():
    @shield_mcp_tool
    def crashing_tool():
        raise ZeroDivisionError("division by zero simulation")

    res = crashing_tool()
    assert res["status"] == "INTERNAL_ERROR"
    assert "ZeroDivisionError" in res["error"]
