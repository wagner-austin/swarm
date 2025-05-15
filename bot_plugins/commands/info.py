#!/usr/bin/env python
"""
plugins/commands/info.py
------------------------
Summary: Info command plugin. Displays bot information.
Usage:
  @bot info
"""

from discord.ext import commands



class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="info")
    async def info(self, ctx):
        try:
            await ctx.send("Hi! I’m the volunteer-coordination bot.")
        except Exception:
            await ctx.send("An internal error occurred. Please try again later.")

async def setup(bot):
    await bot.add_cog(Info(bot))

# End of plugins/commands/info.py