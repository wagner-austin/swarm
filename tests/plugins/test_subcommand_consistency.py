"""
File: tests/plugins/test_subcommand_consistency.py
--------------------------------------------------
Meta-tests to confirm each plugin (and its subcommands) is tested for valid/invalid usage.
The idea is to:
  1) Enumerate all plugins via get_all_plugins().
  2) Attempt to see which subcommands might exist by scanning docstrings or a known dictionary if present.
  3) Test each recognized subcommand with some minimal valid usage (if feasible).
  4) Test an invalid subcommand -> Expect usage text with "unknown subcommand".
"""

import pytest
from plugins.manager import get_all_plugins
from core.state import BotStateMachine
from parsers.plugin_arg_parser import PluginArgError

def _is_subcommand_based(docstring: str) -> bool:
    if not docstring:
        return False
    return "subcommands:" in docstring.lower()

def _extract_subcommands(docstring: str) -> list:
    if not docstring:
        return []
    subcmds = []
    lines = docstring.splitlines()
    for line in lines:
        line_lower = line.strip().lower()
        if line_lower and not line_lower.startswith("usage") and not line_lower.startswith("@bot"):
            tokens = line.strip().split()
            if tokens and not tokens[0].startswith("-") and not tokens[0].startswith("@bot"):
                subcmds.append(tokens[0])
    return subcmds

@pytest.mark.parametrize("plugin_name_info", list(get_all_plugins().items()))
def test_subcommand_based_plugins(plugin_name_info):
    """
    For each plugin, if it's subcommand-based, test:
      - Attempt each recognized subcommand with minimal usage
      - Attempt an invalid subcommand -> Expect usage text with "unknown subcommand".
    """
    canonical_command, plugin_data = plugin_name_info
    docstring = (plugin_data["function"].__doc__ or "").strip()
    if not _is_subcommand_based(docstring):
        pytest.skip(f"Plugin '{canonical_command}' is not subcommand-based, skipping meta-test.")

    recognized_subcmds = _extract_subcommands(docstring)
    if not recognized_subcmds:
        pytest.skip(f"Plugin '{canonical_command}' subcommand-based but no subcommands recognized from docstring.")

    plugin_func = plugin_data["function"]

    # Test each recognized subcommand with minimal usage
    for subcmd in recognized_subcmds:
        try:
            response = plugin_func(subcmd, "+dummy", BotStateMachine())
            assert isinstance(response, str)
        except PluginArgError:
            pass

    # Test an invalid subcommand
    invalid_response = plugin_func("invalidsubcmd", "+dummy", BotStateMachine())
    assert "unknown subcommand" in invalid_response.lower()
    assert "usage" in invalid_response.lower()

# End of tests/plugins/test_subcommand_consistency.py