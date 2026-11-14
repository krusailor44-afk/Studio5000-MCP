"""
Standalone CLI Client for Studio 5000 Live MCP Server.
Allows testing tools directly from PowerShell / Terminal without launching an AI harness.
"""

import os
import sys
import argparse
import json

from studio5000_live_mcp.server import (
    read_routine,
    read_tag,
    propose_edit,
    test_edits,
    untest_edits,
    assemble_edits,
    get_client
)


def main():
    parser = argparse.ArgumentParser(description="Studio 5000 Live CLI Tester")
    parser.add_argument("--acd-path", default=r"C:\Sonic\PLC\SpectrumBrands_2278_12_11_2025_A.ACD", help="Path to .ACD project")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # read-routine
    p_routine = subparsers.add_parser("read-routine", help="Read ladder logic of a routine")
    p_routine.add_argument("--program", required=True, help="Program name (e.g. Sonic_Mixing_Skid)")
    p_routine.add_argument("--routine", required=True, help="Routine name (e.g. MainRoutine)")

    # read-tag
    p_tag = subparsers.add_parser("read-tag", help="Read online tag value")
    p_tag.add_argument("--tag", required=True, help="Tag name")
    p_tag.add_argument("--program", default=None, help="Program name (optional)")

    # test-edits
    p_test = subparsers.add_parser("test-edits", help="Activate test mode on controller")
    p_test.add_argument("--program", default="MainProgram")
    p_test.add_argument("--routine", default="MainRoutine")

    # untest-edits
    p_untest = subparsers.add_parser("untest-edits", help="Revert controller to original logic")
    p_untest.add_argument("--program", default="MainProgram")
    p_untest.add_argument("--routine", default="MainRoutine")

    # assemble-edits
    p_assemble = subparsers.add_parser("assemble-edits", help="Finalize edits permanently")
    p_assemble.add_argument("--program", default="MainProgram")
    p_assemble.add_argument("--routine", default="MainRoutine")
    p_assemble.add_argument("--confirm", action="store_true", help="Explicit human confirmation flag")

    args = parser.parse_args()

    os.environ["STUDIO5000_ACD_PATH"] = args.acd_path

    if args.command == "read-routine":
        res = read_routine(args.program, args.routine)
        print(json.dumps(res, indent=2))

    elif args.command == "read-tag":
        res = read_tag(args.tag, args.program)
        print(json.dumps(res, indent=2))

    elif args.command == "test-edits":
        res = test_edits(args.program, args.routine)
        print(json.dumps(res, indent=2))

    elif args.command == "untest-edits":
        res = untest_edits(args.program, args.routine)
        print(json.dumps(res, indent=2))

    elif args.command == "assemble-edits":
        res = assemble_edits(args.program, args.routine, confirmed=args.confirm)
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
