"""
File: tests/plugins/test_plugin_discovery.py
--------------------------------------------
Tests for plugin discovery using pkgutil in plugins/manager.py.
Verifies that plugins are correctly discovered, loaded, and reloaded.
Also includes a test simulating newly added or removed plugin modules at runtime (reload behavior with modified files).
"""

import pkgutil
import importlib
import types
from unittest.mock import patch
from plugins import manager

def test_load_plugins_populates_registry():
    # Clear any existing plugins.
    manager.clear_plugins()
    # Load plugins from the plugins package.
    manager.load_plugins()
    plugins_dict = manager.get_all_plugins()
    # We expect that at least one plugin is loaded (assuming there are plugin modules present).
    assert isinstance(plugins_dict, dict)
    assert len(plugins_dict) > 0

def test_reload_plugins_clears_and_reloads():
    # Load plugins initially.
    manager.load_plugins()
    initial_plugins = manager.get_all_plugins().copy()
    # Now reload plugins.
    manager.reload_plugins()
    reloaded_plugins = manager.get_all_plugins()
    # The registry should not be empty after reloading.
    assert len(reloaded_plugins) > 0
    # Although the references might be updated, the keys should remain consistent.
    assert set(initial_plugins.keys()) == set(reloaded_plugins.keys())

def test_reload_plugins_with_dynamic_changes():
    """
    Test reload_plugins() after dynamically adding/removing a plugin file.
    Mocks pkgutil.walk_packages to simulate plugin modules being discovered or removed at runtime.
    Ensures the registry is updated accordingly.
    """
    manager.clear_plugins()

    # Simulate an initial list of discovered plugin modules
    initial_module_list = [
        pkgutil.ModuleInfo(None, "plugins.commands.existing_a", False),
        pkgutil.ModuleInfo(None, "plugins.commands.existing_b", False),
    ]

    # Then simulate that 'existing_b' is removed and 'new_plugin' is added
    updated_module_list = [
        pkgutil.ModuleInfo(None, "plugins.commands.existing_a", False),
        pkgutil.ModuleInfo(None, "plugins.commands.new_plugin", False),
    ]

    call_count = {"count": 0}

    def fake_walk_packages(path, prefix):
        call_count["count"] += 1
        if call_count["count"] == 1:
            return initial_module_list
        else:
            return updated_module_list

    real_import_module = importlib.import_module

    with patch.object(pkgutil, "walk_packages", side_effect=fake_walk_packages):
        with patch("importlib.import_module") as mock_import:
            def import_side_effect(name, *args, **kwargs):
                if name in {
                    "plugins.commands.existing_a",
                    "plugins.commands.existing_b",
                    "plugins.commands.new_plugin",
                }:
                    dummy_module = types.ModuleType(name)
                    final_part = name.split(".")[-1]
                    code = f'''
from plugins.manager import plugin

@plugin(commands=["{final_part}"], canonical="{final_part}", help_visible=True)
def dummy_plugin_command(args, sender, state_machine, msg_timestamp=None):
    return "Hello from {final_part}"
'''
                    exec(code, dummy_module.__dict__)
                    return dummy_module
                else:
                    return real_import_module(name, *args, **kwargs)

            mock_import.side_effect = import_side_effect

            # First load: should see existing_a, existing_b
            manager.load_plugins()
            initial_plugins = manager.get_all_plugins().copy()
            assert any("existing_a" in k for k in initial_plugins.keys()), (
                "Expected 'existing_a' plugin to be loaded initially."
            )
            assert any("existing_b" in k for k in initial_plugins.keys()), (
                "Expected 'existing_b' plugin to be loaded initially."
            )

            # Second load (reload): should remove 'existing_b' and add 'new_plugin'
            manager.reload_plugins()
            updated_plugins = manager.get_all_plugins()
            assert not any("existing_b" in k for k in updated_plugins.keys()), (
                "Expected 'existing_b' plugin to be removed on reload."
            )
            assert any("new_plugin" in k for k in updated_plugins.keys()), (
                "Expected 'new_plugin' to be loaded on reload."
            )

# End of tests/plugins/test_plugin_discovery.py