#!/usr/bin/env python
"""
tests/cli/test_cli_tools.py - Updated tests for cli_tools.py.
----------------------------------------------------
Verifies CLI dispatch behavior with the dynamic plugin system.
Tests ensure that unknown or missing commands print usage help and that
valid commands (check in, check out, volunteer status, and help) are recognized.
"""

from tests.cli.cli_test_helpers import run_cli_command

def test_cli_no_subcommand():
    """
    Verify that calling cli_tools.py without any subcommand prints top-level usage help.
    """
    output_data = run_cli_command([])
    stdout = output_data["stdout"].lower()
    assert "usage:" in stdout

def test_cli_unknown_command():
    """
    Test that calling cli_tools.py with an unknown command prints usage or help text.
    """
    output_data = run_cli_command(["foobar"])
    stdout = output_data["stdout"].lower()
    assert "usage:" in stdout

def test_cli_partial_known_command():
    """
    Test that a partial near-match command like 'volunteer statu' shows usage help.
    """
    output_data = run_cli_command(["volunteer statu"])
    stdout = output_data["stdout"].lower()
    assert "usage:" in stdout

def test_cli_help_command():
    """
    Verify that invoking the help command prints the dynamically generated usage information.
    """
    output_data = run_cli_command(["help"])
    stdout = output_data["stdout"].lower()
    # The help output should list the currently registered commands.
    assert "check in" in stdout
    assert "check out" in stdout
    assert "volunteer status" in stdout
    assert "help" in stdout

def test_cli_check_in_command():
    """
    Test the 'check in' command.
    Since volunteer data is not set via CLI here, verify that the command is recognized
    (i.e. it does not print usage help).
    """
    output_data = run_cli_command(["check in"])
    stdout = output_data["stdout"].lower()
    assert not stdout.startswith("usage:")

def test_cli_check_out_command():
    """
    Test the 'check out' command.
    """
    output_data = run_cli_command(["check out"])
    stdout = output_data["stdout"].lower()
    assert not stdout.startswith("usage:")

def test_cli_volunteer_status_command():
    """
    Test the 'volunteer status' command.
    """
    output_data = run_cli_command(["volunteer status"])
    stdout = output_data["stdout"].lower()
    # The expected output should not be the usage help.
    assert not stdout.startswith("usage:")

# End of tests/cli/test_cli_tools.py