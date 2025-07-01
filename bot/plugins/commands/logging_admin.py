"""Runtime logging controls via slash commands.

Owner can query and change the root log level without restarting the bot:

    /loglevel                → shows current level
    /loglevel level: DEBUG   → sets root logger to DEBUG
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from bot.utils.discord_interactions import safe_send

_VALID_LEVELS: tuple[str, ...] = (
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
)
_SPACER = " │ "


class LoggingAdmin(commands.Cog):
    """Administrative commands for live logging control."""

    def __init__(self, bot: commands.Bot) -> None:  # noqa: D401 – simple description
        self.bot = bot

    # ---------------------------------------------------------------------
    # slash command: /loglevel
    # ---------------------------------------------------------------------

    @discord.app_commands.command(name="loglevel", description="Get or set the runtime log level.")
    @discord.app_commands.describe(level="New log level: DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    async def loglevel(self, interaction: discord.Interaction, level: str | None = None) -> None:  # noqa: D401
        """Show or change the root log level at runtime (owner-only)."""

        # Only the bot owner may adjust log levels.
        # Resolve owner dynamically if not cached
        owner_id = self.bot.owner_id
        if owner_id is None:
            try:
                app_owner = (await self.bot.application_info()).owner
                owner_id = app_owner.id if app_owner else None
            except Exception:
                owner_id = None

        if owner_id is None or interaction.user.id != owner_id:
            await safe_send(
                interaction, "❌ Only the bot owner can use this command.", ephemeral=True
            )
            return

        root_logger = logging.getLogger()
        if level is None:
            current = logging.getLevelName(root_logger.level)
            embed = discord.Embed(
                title="Current log level",
                description=f"🔎 **{current}**",
                colour=discord.Colour.blue(),
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        level_upper = level.upper()
        if level_upper not in _VALID_LEVELS:
            choices = ", ".join(_VALID_LEVELS)
            embed_err = discord.Embed(
                title="Invalid log level",
                description=f"❌ `{level}` is not valid.{_SPACER}Choose: {choices}",
                colour=discord.Colour.red(),
            )
            await safe_send(interaction, embed=embed_err, ephemeral=True)
            return

        root_logger.setLevel(level_upper)
        # Also update existing handler levels so they don't filter below the new root.
        for handler in root_logger.handlers:
            handler.setLevel(level_upper)

        embed_ok = discord.Embed(
            title="Log level updated",
            description=f"✅ Log level set to **{level_upper}**",
            colour=discord.Colour.orange(),
        )
        await safe_send(interaction, embed=embed_ok, ephemeral=True)
