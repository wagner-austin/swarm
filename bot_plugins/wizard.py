from bot_core.conversation import Conversation
from bot_plugins.abstract import BasePlugin

class WizardPlugin(BasePlugin):
    """
    Mix-in for wizard-style multi-step plugins.
    Subclasses must define:
      - self.command_name: str
      - self.steps: dict[str, callable]
    """
    async def run_command(self, ctx, args):
        # Get user_id as string, fallback to None if not present
        user_id = str(getattr(getattr(ctx, 'author', None), 'id', None))
        if not user_id or not hasattr(self, 'command_name') or not hasattr(self, 'steps'):
            return "Wizard misconfigured."

        convo = Conversation.get(user_id, self.command_name)
        if convo is None:
            convo = Conversation(user_id, self.command_name, {"step": "start"})
            handler = self.steps.get("start")
            if handler is None:
                return "Wizard is confused. Type cancel to reset."
            reply = await handler(ctx, convo)
        else:
            step = convo.data.get("step", "start")
            handler = self.steps.get(step)
            if handler is None:
                return "Wizard is confused. Type cancel to reset."
            reply = await handler(ctx, convo, args.strip())
        convo.touch()
        return reply
