import tomllib
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from swarm.frontends.discord.discord_interactions import safe_send


def get_bot_version() -> str:
    """Get the swarm version from pyproject.toml."""
    try:
        project_root = Path(__file__).parents[3]  # Go up three directories to project root
        pyproject_path = project_root / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            pyproject_data = tomllib.load(f)
            return str(pyproject_data["project"]["version"])
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


class About(commands.Cog):
    def __init__(self, discord_bot: commands.Bot) -> None:
        super().__init__()
        self.bot = discord_bot

    @app_commands.command(name="about", description="Show information about the swarm.")
    async def about(self, interaction: discord.Interaction) -> None:
        """Display basic information about the swarm."""
        assert self.bot.user is not None  # narrow Optional for mypy
        embed = discord.Embed(
            title=f"{self.bot.user.name} - About",
            description=f"An AI-powered task execution system. Version: {get_bot_version()}\nRunning on discord.py {discord.__version__}.",
            color=discord.Color.blue(),
        )
        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        embed.add_field(name="Developer", value="Austin Wagner", inline=False)
        embed.add_field(
            name="Source Code",
            value="[Source Code](https://github.com/wagner-austin/swarm)",
            inline=False,
        )

        await safe_send(interaction, embed=embed, ephemeral=True)
