import pytest
from plugins.commands.announce_wizard import AnnounceWizard
from core.conversation import _WIZARDS

class FakeChannel:
    def __init__(self):
        self.sent = []
    async def send(self, msg):
        self.sent.append(msg)

class FakeAuthor:
    def __init__(self, id):
        self.id = id

class FakeCtx:
    def __init__(self, user_id):
        self.author = FakeAuthor(user_id)
        self.channel = FakeChannel()
    async def send(self, msg):
        await self.channel.send(msg)

@pytest.mark.asyncio
async def test_announce_wizard_flow():
    _WIZARDS.clear()
    wiz = AnnounceWizard()
    ctx = FakeCtx(user_id=123)

    # Start wizard
    reply = await wiz.run_command(ctx, "")
    assert "What announcement" in reply
    assert len(_WIZARDS) == 1

    # Provide body
    reply = await wiz.run_command(ctx, "Hello world!")
    assert "Preview" in reply
    assert "send" in reply
    assert len(_WIZARDS) == 1

    # Send
    reply = await wiz.run_command(ctx, "send")
    assert "Announcement sent" in reply
    assert len(_WIZARDS) == 0
