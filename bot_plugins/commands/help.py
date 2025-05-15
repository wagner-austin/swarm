#!/usr/bin/env python
"""
File: plugins/commands/help.py
------------------------------
Summary: Help command plugin. Lists available commands.

Now only shows commands that the user has permission to use, based on their volunteer role.
Focuses on modular, unified, consistent code that facilitates future updates.
"""

from discord.ext import commands

HELP_USAGE = "Usage: !help"
INTERNAL_ERROR = "An internal error occurred. Please try again later."

# If you need to list commands, you may want to use bot.commands or similar.


from discord.ext import commands

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help(self, ctx):
        lines = []
        for cmd in self.bot.walk_commands():
            if cmd.hidden:
                continue
            lines.append(f"**{cmd.qualified_name}** – {cmd.help or '…'}")
        await ctx.send("\n".join(lines) or "No commands available.")

async def setup(bot):
    await bot.add_cog(Help(bot))

# End of plugins/commands/help.py