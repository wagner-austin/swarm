#!/usr/bin/env python
"""
tests/cli/cli_test_helpers.py - Helper functions for CLI tests.
----------------------------------------------------------------
Provides a unified helper to simulate command-line invocations of cli_tools.py,
capturing both stdout and stderr. We still rely on this to test the end-to-end
CLI behavior including argparse and plugin dispatch.
"""

import sys
import io

def run_cli_command(command_args):
    """
    run_cli_command - Helper function to simulate command-line invocation of cli_tools.py.
    Captures both stdout and stderr.
    
    Args:
        command_args (list): List of command arguments (e.g. ["list-volunteers"]).
    
    Returns:
        dict: A dictionary with keys 'stdout' and 'stderr' containing the captured outputs.
    """
    original_argv = sys.argv
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    try:
        sys.argv = ["cli_tools.py"] + command_args
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr
        from cli.cli_tools import main as cli_main
        try:
            cli_main()
        except SystemExit:
            # Argparse or the code may call sys.exit; we catch it
            pass
        return {"stdout": captured_stdout.getvalue(), "stderr": captured_stderr.getvalue()}
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout
        sys.stderr = original_stderr

# End of tests/cli/cli_test_helpers.py