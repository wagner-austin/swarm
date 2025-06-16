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
from typing import List, Optional

import discord
import yaml
from discord import app_commands
from discord.ext import commands

# Re-export internals we need – kept under ``noqa`` to silence ruff unused-import
from bot.ai.personas import (  # noqa: F401 – re-export for tests
    PERSONALITIES,
    _CUSTOM_DIR,
    _load as _reload,  # helper to (re)load from YAML
    Persona,
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
    # Static helpers for test-suite (no Discord required)
    # ---------------------------------------------------------------------

    @staticmethod
    def _write(cls: type["PersonaAdmin"], name: str, data: Persona) -> None:
        """Exposed write helper so tests can call
        ``PersonaAdmin._write(PersonaAdmin, ...)`` without instantiating.
        The *self* argument is ignored (it will receive the class object).
        """

        _write_yaml(name, data)

    # NOTE: the *delete* name is required by tests that call
    # ``PersonaAdmin.delete(PersonaAdmin, None, name="foo")``. We purposefully
    # implement it as **synchronous staticmethod** so that calling code can
    # invoke it without awaiting.    The first two positional arguments (*self*
    # and *interaction*) are discarded.

    @staticmethod
    def delete(
        cls: type["PersonaAdmin"],
        _interaction: discord.Interaction | None = None,
        *,
        name: str,
    ) -> None:
        _delete_yaml(name)

    # ---------------------------------------------------------------------
    # /persona add
    # ---------------------------------------------------------------------

    @app_commands.command(name="add", description="Create or overwrite a persona")
    @app_commands.default_permissions(administrator=True)
    async def add(  # noqa: D401 – discord handler
        self,
        interaction: discord.Interaction,
        name: str,
        prompt_text: str,
        allowed_users: Optional[str] = None,
    ) -> None:
        """Create or overwrite a persona.

        ``allowed_users`` is an optional comma-separated list of Discord user
        IDs.  If omitted the persona is visible to everyone.
        """

        users: Optional[List[int]] = (
            [int(u) for u in allowed_users.split(",")] if allowed_users else None
        )
        _write_yaml(name, {"prompt": prompt_text, "allowed_users": users})

        await interaction.response.send_message(
            f"Persona **{name}** saved.", ephemeral=True
        )

    # ------------------------------------------------------------------
    # /persona delete (async version used at runtime; sync stub above for tests)
    # ------------------------------------------------------------------

    @app_commands.command(name="delete", description="Delete custom persona")
    @app_commands.default_permissions(administrator=True)
    async def delete_cmd(self, interaction: discord.Interaction, name: str) -> None:
        """Delete a custom persona (if it exists)."""

        if _delete_yaml(name):
            msg = f"Persona **{name}** removed."
        else:
            msg = "No such custom persona."
        await interaction.response.send_message(msg, ephemeral=True)

    # ------------------------------------------------------------------
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
        await interaction.response.send_message(
            "\n".join(lines) or "None", ephemeral=True
        )

    # ------------------------------------------------------------------
    # /persona edit – partial update (supports interactive modal)
    # ------------------------------------------------------------------

    @app_commands.command(
        name="edit",
        description="Modify an existing persona (leave blank args to open a modal)",
    )
    @app_commands.default_permissions(administrator=True)
    async def edit_cmd(  # noqa: D401 – discord handler
        self,
        interaction: discord.Interaction,
        name: str,
        prompt_text: str | None = None,
        allowed_users: str | None = None,
    ) -> None:
        """Partially update an existing persona without resupplying all fields."""

        # --- ensure persona exists ---
        if name not in PERSONALITIES:
            await interaction.response.send_message("No such persona.", ephemeral=True)
            return

        # Interactive modal path – no arguments given
        if prompt_text is None and allowed_users is None:
            current = PERSONALITIES[name]

            class _EditModal(discord.ui.Modal, title=f"Edit persona: {name}"):
                prompt_input: discord.ui.TextInput[discord.ui.Modal]
                users_input: discord.ui.TextInput[discord.ui.Modal]

                def __init__(self) -> None:  # noqa: D401 – simple init
                    super().__init__()
                    self.prompt_input = discord.ui.TextInput(
                        label="Prompt",
                        style=discord.TextStyle.paragraph,
                        default=current["prompt"],
                        required=False,
                    )
                    self.users_input = discord.ui.TextInput(
                        label="Allowed user IDs (comma-separated)",
                        default=",".join(
                            str(u) for u in (current["allowed_users"] or [])
                        ),
                        required=False,
                    )
                    self.add_item(self.prompt_input)
                    self.add_item(self.users_input)

                async def on_submit(self, interaction: discord.Interaction) -> None:
                    new_prompt = self.prompt_input.value or None
                    new_users_raw = self.users_input.value or None
                    new_users = (
                        [int(u.strip()) for u in new_users_raw.split(",") if u.strip()]
                        if new_users_raw
                        else None
                    )
                    from typing import cast

                    data: Persona = cast(
                        Persona,
                        {
                            "prompt": new_prompt or current["prompt"],
                            "allowed_users": new_users,
                        },
                    )
                    _write_yaml(name, data)
                    await interaction.response.send_message(
                        f"Persona **{name}** updated via modal.", ephemeral=True
                    )

            await interaction.response.send_modal(_EditModal())
            return

        # ---- CLI-style args path ----
        current = PERSONALITIES[name].copy()
        if prompt_text is not None:
            current["prompt"] = prompt_text
        if allowed_users is not None:
            current["allowed_users"] = (
                [int(u) for u in allowed_users.split(",")] if allowed_users else None
            )

        _write_yaml(name, current)
        await interaction.response.send_message(
            f"Persona **{name}** updated.", ephemeral=True
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
            await interaction.response.send_message(
                f"YAML error: {exc}", ephemeral=True
            )
            return

        from bot.ai.personas import _SECRET_FILE, PERSONALITIES

        _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SECRET_FILE.write_text(text, encoding="utf-8")

        # hot reload – merge secrets last
        PERSONALITIES.update(data)
        await interaction.response.send_message(
            "Secret personas imported 👍", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:  # noqa: D401 – mandated signature
    """Standard extension entry-point used by discord-py."""

    await bot.add_cog(PersonaAdmin(bot))
