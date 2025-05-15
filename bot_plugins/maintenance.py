from discord.ext import commands, tasks
import logging
from db.backup import create_backup, _prune_backups
from bot_core.settings import settings

log = logging.getLogger(__name__)

class Maintenance(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.backup.start()

    @tasks.loop(seconds=settings.backup_interval)
    async def backup(self):
        try:
            path = create_backup()
            log.info("Periodic backup created at %s", path)
            _prune_backups(settings.backup_retention)
        except Exception:
            log.exception("Backup task failed")

    @backup.before_loop
    async def _wait_until_ready(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Maintenance(bot))
