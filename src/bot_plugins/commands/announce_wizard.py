from discord.ext import commands
from bot_plugins.typing import Ctx
import logging
from typing import Any

logger = logging.getLogger(__name__)

USAGE_ANNOUNCE = "Usage: !announce <text>"
USAGE_CANCEL = "Usage: !announce cancel"


class AnnounceWizard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.pending: dict[int, dict[str, Any]] = {}
        self.steps = {
            "start": self._ask_text,
            "confirm": self._preview,
            "send?": self._send_or_cancel,
        }

    async def _ask_text(self, ctx: Ctx, convo: dict[str, Any]) -> None:
        convo["step"] = "confirm"
        await ctx.send(
            "What announcement would you like to send? Type your text or 'cancel'."
        )

    async def _preview(self, ctx: Ctx, convo: dict[str, Any], text: str) -> None:
        if text.strip().lower() == "cancel":
            await self._cancel(ctx, convo)
            return
        convo["text"] = text
        convo["step"] = "send?"
        await ctx.send(
            f"Preview:\n{text}\n\nType 'send' to post, or 'cancel' to abort."
        )
        return

    async def _send_or_cancel(self, ctx: Ctx, convo: dict[str, Any], cmd: str) -> None:
        cmd = cmd.strip().lower()
        if cmd == "cancel":
            await self._cancel(ctx, convo)
            return
        elif cmd == "send":
            announcement = convo.get("text", "<no text>")
            # await ctx.send(announcement)  # Uncomment for real bot
            await ctx.send(f"Announcement sent!\n{announcement}")
            user_id = ctx.author.id
            if user_id in self.pending:
                del self.pending[user_id]
            return
        else:
            await ctx.send("Please type 'send' to post or 'cancel' to abort.")
            return

    async def _cancel(self, ctx: Ctx, convo: dict[str, Any]) -> None:
        await ctx.send("Wizard cancelled.")
        return

    @commands.command(name="announce")
    @commands.has_role("admin")
    async def announce(self, ctx: Ctx, *, text: str | None = None) -> None:
        user_id = ctx.author.id
        if user_id in self.pending:
            convo = self.pending[user_id]
            step = convo.get("step", "start")
            if step == "confirm" and text is not None:
                await self._preview(ctx, convo, text)
            elif step == "send?" and text is not None:
                await self._send_or_cancel(ctx, convo, text)
            else:
                await ctx.send("Please continue or type 'cancel'.")
                return
        else:
            # Start new conversation
            self.pending[user_id] = {"step": "confirm"}
            await ctx.send(
                "What announcement would you like to send? Type your text or 'cancel'."
            )
            return

    @commands.command(name="cancel")
    async def cancel(self, ctx: Ctx) -> None:
        user_id = ctx.author.id
        if user_id in self.pending:
            del self.pending[user_id]
            await ctx.send("Announcement wizard cancelled.")
            return
        else:
            await ctx.send("No active announcement wizard to cancel.")
            return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AnnounceWizard(bot))
