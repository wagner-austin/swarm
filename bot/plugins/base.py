from discord.ext import commands


class BaseCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        # Ensure commands are properly associated with this cog instance
        # It's generally good practice for discord.py to handle this,
        # but explicitly setting can resolve some edge cases or ensure consistency
        # if commands are defined in a way that might not automatically link them.
        # However, discord.py v2.0+ largely handles cog assignment automatically
        # when commands are defined as methods within the Cog class.
        # This loop might be more relevant for commands added dynamically or in older versions.
        # For standard method-based commands, this might be redundant but harmless.
        # `walk_commands()` yields every command registered to this cog,
        # recursively, so sub-commands inside groups are included.
        for cmd in self.walk_commands():
            cmd.cog = self
