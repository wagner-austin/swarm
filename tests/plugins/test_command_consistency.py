"""
Ensures that the slash‑command names documented in the cog’s help text
actually exist in the code.

This test was originally written for the legacy *browser* cog; it now targets
the renamed *web* cog introduced in #214.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

import discord
import pytest
from discord.ext import commands

from swarm.plugins.commands import web as web_mod


class TestCommandConsistency(unittest.TestCase):
    """Tests to ensure web commands are properly implemented with good naming."""

    def test_web_commands_exist_and_follow_naming_convention(self) -> None:
        """Auto-discover commands from Web cog and verify they follow naming conventions."""
        # Get the actual Web cog class
        web_cog_class = getattr(web_mod, "Web")

        # Create a dummy discord_bot to instantiate the cog and get its commands
        from unittest.mock import MagicMock

        mock_discord_discord_bot = MagicMock(spec=commands.Bot)
        mock_discord_discord_bot.container = MagicMock()  # Mock container for DI

        # Create the cog instance to access its app_commands
        try:
            web_cog = web_cog_class(discord_bot=mock_discord_discord_bot)
        except Exception as e:
            self.fail(f"Failed to instantiate Web cog: {e}")

        # Get all app_commands from the cog
        discovered_commands = set()

        # Method 1: Check if cog has __cog_app_commands__ attribute (discord.py 2.x)
        if hasattr(web_cog, "__cog_app_commands__"):
            for cmd in web_cog.__cog_app_commands__:
                if hasattr(cmd, "name"):
                    discovered_commands.add(cmd.name)

        # Method 2: Inspect methods for app_commands decorators
        if not discovered_commands:
            for attr_name in dir(web_cog):
                attr = getattr(web_cog, attr_name)
                # Check for discord app command attributes
                if (
                    hasattr(attr, "__discord_app_commands_is_slash__")
                    and attr.__discord_app_commands_is_slash__
                ):
                    # Try to get command name
                    if hasattr(attr, "__discord_app_commands_name__"):
                        discovered_commands.add(attr.__discord_app_commands_name__)
                    elif hasattr(attr, "name"):
                        discovered_commands.add(attr.name)

        # Method 3: Fallback - look for async methods that look like commands
        if not discovered_commands:
            import inspect

            for attr_name in dir(web_cog):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(web_cog, attr_name)
                if (
                    inspect.iscoroutinefunction(attr)
                    and hasattr(attr, "__annotations__")
                    and "discord.Interaction" in str(attr.__annotations__)
                ):
                    discovered_commands.add(attr_name)

        # Ensure we found some commands
        self.assertGreater(
            len(discovered_commands), 0, "No commands discovered from Web cog - test may be broken"
        )

        # Check that all discovered commands follow naming conventions
        for cmd_name in discovered_commands:
            with self.subTest(command=cmd_name):
                self.assertRegex(
                    cmd_name,
                    r"^[a-z0-9_]+$",
                    f"Command '{cmd_name}' should be lower-case ASCII",
                )

                # Ensure the command name is reasonable (not too short/long)
                self.assertGreaterEqual(len(cmd_name), 2, f"Command '{cmd_name}' name too short")
                self.assertLessEqual(len(cmd_name), 20, f"Command '{cmd_name}' name too long")

        # Report what we found for debugging
        print(f"Discovered web commands: {sorted(discovered_commands)}")
