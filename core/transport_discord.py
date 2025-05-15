import os
import asyncio
import tempfile
import shutil
from typing import Callable, Any, Awaitable, Optional

import discord
from discord import Intents, Message

from core.transport import Transport
from parsers.message_parser import parse_message

class DiscordTransport(Transport):
    def __init__(self):
        self.client = None
        self.token = os.getenv("DISCORD_TOKEN")
        if not self.token:
            raise RuntimeError("DISCORD_TOKEN not set in environment.")
        self._on_message = None
        self._running = False

    async def send_message(self, channel, content: str = "", files: Optional[list[str]] = None):
        """
        Send a message to a Discord channel. Accepts either a channel_id (int) or a discord.abc.Messageable object.
        """
        if not self.client:
            raise RuntimeError("Discord client is not running.")
        # Accept either channel_id or channel object
        if isinstance(channel, int):
            channel_obj = self.client.get_channel(channel)
            if channel_obj is None:
                raise ValueError(f"Channel {channel} not found.")
        else:
            channel_obj = channel
        discord_files = []
        try:
            if files:
                for fpath in files:
                    discord_files.append(discord.File(fpath))
            await channel_obj.send(content=content, files=discord_files)
        finally:
            for f in discord_files:
                f.close()

    async def receive_messages(self):
        """
        Async generator for unit testing: yields ParsedMessage objects as received.
        """
        if not self.client:
            raise RuntimeError("Discord client is not running.")
        queue = asyncio.Queue()

        async def _on_message(msg: Message):
            if msg.author.bot:
                return
            parsed = parse_message(msg.content)
            setattr(parsed, "attachments", [att.url for att in msg.attachments])
            await queue.put(parsed)

        self.client.add_listener(_on_message, 'on_message')
        while True:
            parsed = await queue.get()
            yield parsed

    async def start(self, on_message: Callable[[Any, Message], Awaitable[None]]):
        intents = Intents.default()
        intents.message_content = True
        self.client = discord.Client(intents=intents)
        self._on_message = on_message
        self._running = True

        # Register event handlers (add more if needed later)
        @self.client.event
        async def on_message(msg: Message):
            if msg.author.bot:
                return
            temp_dir = tempfile.mkdtemp(prefix="discord_attach_")
            attachment_paths = []
            try:
                for att in msg.attachments:
                    save_path = os.path.join(temp_dir, att.filename)
                    await att.save(save_path)
                    attachment_paths.append(save_path)
                parsed = parse_message(msg.content)
                setattr(parsed, "attachments", attachment_paths)
                await self._on_message(parsed, msg)
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        # Future: register on_message_edit, on_message_delete here as needed

        await self.client.start(self.token)
