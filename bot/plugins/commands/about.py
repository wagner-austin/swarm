import discord
from discord import app_commands
from discord.ext import commands


class About(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    @app_commands.command(name="about", description="Show information about the bot.")
    async def about(self, interaction: discord.Interaction) -> None:
        """Displays basic information about the bot."""
        assert self.bot.user is not None  # narrow Optional for mypy
        embed = discord.Embed(
            title=f"{self.bot.user.name} - About",
            description=f"A helpful Discord bot. Version: 1.0.0\nRunning on discord.py {discord.__version__}.",
            color=discord.Color.blue(),
        )
        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        embed.add_field(name="Developer", value="Austin Wagner", inline=False)
        embed.add_field(
            name="Source Code",
            value="[Link to your bot's source code](https://github.com/wagner-austin/DiscordBot)",
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(About(bot))
