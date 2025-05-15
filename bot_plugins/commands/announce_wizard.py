from bot_plugins.wizard import WizardPlugin
from bot_core.conversation import _WIZARDS

def plugin(commands, canonical, required_role):
    # Dummy decorator for demonstration; replace with real one if needed
    def decorator(cls):
        return cls
    return decorator

ADMIN = "ADMIN"  # Placeholder for required_role

@plugin(commands=["announce"], canonical="announce", required_role=ADMIN)
class AnnounceWizard(WizardPlugin):
    def __init__(self):
        super().__init__(command_name="announce", help_text="Start an announcement wizard.")
        self.steps = {
            "start": self._ask_text,
            "confirm": self._preview,
            "send?": self._send_or_cancel,
        }

    async def _ask_text(self, ctx, convo):
        convo.data["step"] = "confirm"
        return "What announcement would you like to send? Type your text or 'cancel'."

    async def _preview(self, ctx, convo, text):
        if text.strip().lower() == "cancel":
            return await self._cancel(convo)
        convo.data["text"] = text
        convo.data["step"] = "send?"
        return f"Preview:\n{text}\n\nType 'send' to post, or 'cancel' to abort."

    async def _send_or_cancel(self, ctx, convo, cmd):
        cmd = cmd.strip().lower()
        if cmd == "cancel":
            return await self._cancel(convo)
        elif cmd == "send":
            # Placeholder: replace with actual send logic
            announcement = convo.data.get("text", "<no text>")
            # await ctx.send(announcement)  # Uncomment for real bot
            if convo.id in _WIZARDS:
                del _WIZARDS[convo.id]
            return f"Announcement sent!\n{announcement}"
        else:
            return "Please type 'send' to post or 'cancel' to abort."

    async def _cancel(self, convo):
        if convo.id in _WIZARDS:
            del _WIZARDS[convo.id]
        return "Wizard cancelled."
