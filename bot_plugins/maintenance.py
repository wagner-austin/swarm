from discord.ext import commands, tasks
import logging
from db.backup import create_backup, _prune_backups
from bot_core.settings import settings  # fully typed alias

logger = logging.getLogger(__name__)


class Maintenance(commands.Cog):
    """Cog for periodic maintenance tasks such as database backups."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the Maintenance cog and start the backup loop.

        Args:
            bot: The Discord bot instance.
        """
        self.bot = bot
        self.backup.start()

    @tasks.loop(seconds=settings.backup_interval)
    async def backup(self) -> None:
        """Perform a periodic backup and prune old backups."""
        try:
            path = create_backup()
            logger.info("Periodic backup created at %s", path)
            _prune_backups(settings.backup_retention)
        except Exception:
            logger.exception("Backup task failed")

    @backup.before_loop
    async def _wait_until_ready(self) -> None:
        """Wait until the bot is ready before starting the backup loop."""
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    """Add the Maintenance cog to the bot.

    Args:
        bot: The Discord bot instance.
    """
    await bot.add_cog(Maintenance(bot))
