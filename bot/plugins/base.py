from discord.ext import commands


from .base_di import BaseDIClientCog  # ← add import


class BaseCog(BaseDIClientCog):  # now inherits the DI logic
    """
    Existing convenience base‑class now also provides DI resolution via
    :class:`BaseDIClientCog`.  Nothing else changes.
    """

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)  # BaseDIClientCog takes care of self.bot
        # Ensure commands are properly associated with this cog instance
        # It's generally good practice for discord.py to handle this,
        # but explicitly setting can resolve some edge cases or ensure consistency
        # if commands are defined in a way that might not automatically link them.
        # However, discord.py v2.0+ largely handles cog assignment automatically
        # when commands are defined as methods within the Cog class.
        # This loop might be more relevant for commands added dynamically or in older versions.
        # For standard method-based commands, this might be redundant but harmless.
        # Command‑to‑cog binding is automatic – no manual fix‑up required.
