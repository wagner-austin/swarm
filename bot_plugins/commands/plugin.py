"""
plugins/commands/plugin.py - Plugin management command plugin.
Provides subcommands for listing, enabling, and disabling plugins using Discord's extension system.
Usage:
  !plugins list
  !plugins enable <extension>
  !plugins disable <extension>
"""

from discord.ext import commands

class PluginManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="plugins", invoke_without_command=True)
    @commands.is_owner()
    async def plugins(self, ctx):
        await ctx.send("Usage: !plugins <list|enable|disable> [extension]")

    @plugins.command(name="list")
    async def list_plugins(self, ctx):
        # List loaded extensions
        loaded = list(self.bot.extensions.keys())
        if not loaded:
            await ctx.send("No extensions loaded.")
        else:
            await ctx.send("Loaded extensions:\n" + "\n".join(loaded))

    @plugins.command(name="enable")
    async def enable_plugin(self, ctx, extension: str):
        try:
            await self.bot.load_extension(extension)
            await ctx.send(f"Extension '{extension}' has been enabled.")
        except Exception as e:
            await ctx.send(f"Failed to enable extension '{extension}': {e}")

    @plugins.command(name="disable")
    async def disable_plugin(self, ctx, extension: str):
        try:
            await self.bot.unload_extension(extension)
            await ctx.send(f"Extension '{extension}' has been disabled.")
        except Exception as e:
            await ctx.send(f"Failed to disable extension '{extension}': {e}")

async def setup(bot):
    await bot.add_cog(PluginManager(bot))

# End of plugins/commands/plugin.py