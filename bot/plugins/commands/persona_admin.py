"""Admin-only CRUD slash commands for YAML-backed personas.

This cog exposes a ``/persona`` slash-command group with ``add``, ``delete`` and
``list`` sub-commands so bot operators can manage personas without touching the
filesystem directly.

The implementation intentionally keeps a few **static helper methods** so the
pytest suite can directly call them without spinning up a Discord test client.
Those helpers mutate the in-memory :pydata:`bot.ai.personas.PERSONALITIES` dict
and the underlying YAML files located in
:pydata:`bot.ai.personas._CUSTOM_DIR`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import discord
import yaml
from discord import app_commands
from discord.ext import commands

# Re-export internals we need – kept under ``noqa`` to silence ruff unused-import
from bot.ai.personas import (  # noqa: F401 – re-export for tests
    _CUSTOM_DIR,
    PERSONALITIES,
    Persona,
    _load as _reload,  # helper to (re)load from YAML
)

__all__ = ["PersonaAdmin"]

# ---------------------------------------------------------------------------
# Utility helpers (usable from tests without Discord)
# ---------------------------------------------------------------------------


def _write_yaml(name: str, data: Persona) -> None:
    """(Over)write *name* persona YAML inside :pydata:`_CUSTOM_DIR`."""

    fp: Path = _CUSTOM_DIR / f"{name}.yaml"
    with fp.open("w", encoding="utf-8") as fh:
        yaml.safe_dump({name: data}, fh, sort_keys=False)

    # Hot-reload into in-memory registry
    PERSONALITIES.update({name: data})


def _delete_yaml(name: str) -> bool:
    """Delete *name* persona YAML; return *True* on success, *False* if absent."""

    fp: Path = _CUSTOM_DIR / f"{name}.yaml"
    if not fp.exists():
        return False

    trash: Path = _CUSTOM_DIR / ".trash"
    trash.mkdir(exist_ok=True)
    shutil.move(fp, trash / fp.name)

    PERSONALITIES.pop(name, None)
    return True


# ---------------------------------------------------------------------------
# Cog implementation
# ---------------------------------------------------------------------------


class PersonaAdmin(commands.GroupCog, group_name="persona"):
    """Admin-only CRUD for YAML-backed personas."""

    def __init__(self, bot: commands.Bot):  # noqa: D401 – simple init
        super().__init__()
        self.bot = bot

    # ---------------------------------------------------------------------
    # Static helpers removed – use module-level _write_yaml / _delete_yaml directly
    # ---------------------------------------------------------------------

    # /persona list
    # ------------------------------------------------------------------

    @app_commands.command(name="list", description="Show all personas")
    @app_commands.default_permissions(administrator=True)
    async def list_cmd(self, interaction: discord.Interaction) -> None:  # noqa: D401
        """List built-in and custom personas."""

        lines = [
            f"• **{n}**  ({'custom' if (_CUSTOM_DIR / (n + '.yaml')).exists() else 'built-in'})"
            for n in sorted(PERSONALITIES)
        ]
        await interaction.response.send_message("\n".join(lines) or "None", ephemeral=True)

    # ------------------------------------------------------------------
    # /persona show – read-only display
    # ------------------------------------------------------------------

    @app_commands.command(
        name="show",
        description="Show the prompt for a persona (admin-only, read-only)",
    )
    @app_commands.default_permissions(administrator=True)
    async def show_cmd(  # noqa: D401 – discord handler
        self,
        interaction: discord.Interaction,
        name: str,
    ) -> None:
        """Display the prompt (and allowed users) for the specified persona without allowing edits."""

        # --- ensure persona exists ---
        if name not in PERSONALITIES:
            await interaction.response.send_message("No such persona.", ephemeral=True)
            return

        # Display prompt
        data = PERSONALITIES[name]
        prompt = data["prompt"]
        allowed = data.get("allowed_users")
        allowed_str = (
            "(restricted to: " + ", ".join(str(u) for u in allowed) + ")"
            if allowed
            else "(visible to everyone)"
        )
        await interaction.response.send_message(
            f"**{name}** {allowed_str}\n```text\n{prompt}\n```",
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /persona reload – re-scan YAML on disk and refresh registry
    # ------------------------------------------------------------------

    @app_commands.command(
        name="reload",
        description="Reload all YAML persona files from disk",
    )
    @app_commands.default_permissions(administrator=True)
    async def reload_cmd(self, interaction: discord.Interaction) -> None:
        """Force re-parsing of builtin, custom and secret YAML files."""

        import bot.ai.personas as p  # runtime import

        p.refresh()  # mutate existing dict so all cogs see updates
        await interaction.response.send_message(
            f"Reloaded {len(p.PERSONALITIES)} personas from disk.",
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /persona import – owner-only secret upload
    # ------------------------------------------------------------------

    @app_commands.command(name="import", description="Upload secret personas YAML")
    async def import_cmd(
        self,
        interaction: discord.Interaction,
        attachment: discord.Attachment,
    ) -> None:
        """Owner-only command to store secret personas.

        The supplied *attachment* (a YAML file) is written to the secrets path
        and merged into the in-memory registry without restarting the bot.
        """

        # Permission gate – owners only
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return

        raw: bytes = await attachment.read()

        try:
            text = raw.decode("utf-8")
            data = yaml.safe_load(text) or {}
            # minimal validation
            for key, val in data.items():
                if not isinstance(val, dict) or "prompt" not in val:
                    raise ValueError(f"{key}: missing prompt field")
        except Exception as exc:  # pragma: no cover – tested via path above
            await interaction.response.send_message(f"YAML error: {exc}", ephemeral=True)
            return

        from bot.ai.personas import _SECRET_FILE, PERSONALITIES

        _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SECRET_FILE.write_text(text, encoding="utf-8")

        # hot reload – merge secrets last
        PERSONALITIES.update(data)
        await interaction.response.send_message("Secret personas imported 👍", ephemeral=True)


async def setup(bot: commands.Bot) -> None:  # noqa: D401 – mandated signature
    """Standard extension entry-point used by discord-py."""

    await bot.add_cog(PersonaAdmin(bot))
