import discord
from discord import app_commands
from discord.ext import commands
from typing import Callable, Awaitable, TypeVar, cast


T = TypeVar("T", bound=Callable[..., Awaitable[None]])


def owner_check() -> Callable[[T], T]:
    """Slash-safe equivalent of @commands.is_owner()."""

    async def predicate(interaction: discord.Interaction) -> bool:  # noqa: D401
        bot = cast(commands.Bot, interaction.client)
        return bool(await bot.is_owner(interaction.user))

    return app_commands.check(predicate)


class Shutdown(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    @app_commands.command(
        name="shutdown", description="Cleanly shuts the bot down (owner only)"
    )
    @owner_check()
    async def shutdown(self, interaction: discord.Interaction) -> None:
        """Cleanly shut the bot down (owner-only)."""
        await interaction.response.send_message("Bot is shutting down…", ephemeral=True)
        await interaction.client.close()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shutdown(bot))
