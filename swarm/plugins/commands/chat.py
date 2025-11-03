import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands  # For commands.Bot, commands.Cog

from swarm.ai import personas as personas, providers as _providers
from swarm.ai.contracts import Message
from swarm.core.exceptions import ModelOverloaded
from swarm.core.settings import DISCORD_LIMIT, settings  # fully typed alias

# Centralized interaction helpers
from swarm.frontends.discord.discord_interactions import safe_send
from swarm.history.backends import HistoryBackend
from swarm.plugins.commands.decorators import background_app_command

INTERNAL_ERROR = "An internal error occurred. Please try again later."

logger = logging.getLogger(__name__)

# Note: Avoid binding mutable persona registries at import time to prevent
# stale references across module reloads in tests.

# Global system instruction applied to every persona
DEFAULT_SYSTEM_PROMPT = "Always include your name at the beginning of a response."


class Chat(commands.Cog):
    def __init__(self, discord_bot: commands.Bot, history_backend: HistoryBackend) -> None:
        super().__init__()  # <-- no args
        self.bot = discord_bot  # keep ref for future use
        # Remember last selected personality per channel
        self._channel_persona: dict[int, str] = {}
        # Conversation history backend (DI required – no fallback)
        self._history: HistoryBackend = history_backend
        logger.info("[Chat] Using history backend: %s", type(self._history).__name__)

    async def cog_load(self) -> None:
        """Warm minimal caches to avoid first-hit latency during autocomplete."""
        try:
            # Owner cache warmup is best-effort and strictly time-bounded.
            from swarm.frontends.discord.discord_owner import get_owner

            await asyncio.wait_for(get_owner(self.bot), timeout=1.5)
        except Exception:
            # Non-fatal: if owner cannot be resolved quickly, autocomplete will
            # simply omit owner-only personas until later.
            pass

    async def cog_unload(self) -> None:
        """Clean up resources when the cog is unloaded."""
        # Nothing to clean up – providers manage their own lifecycle.
        return

    @app_commands.command(
        name="chat", description="Chat with the configured LLM (or clear history)"
    )
    @app_commands.describe(
        prompt="What should I ask?",
        clear="If true, reset conversation history instead",
        personality="Pick a persona",
    )
    @background_app_command(defer_ephemeral=True)
    async def chat(
        self,
        interaction: discord.Interaction,
        prompt: str | None = None,
        clear: bool = False,
        personality: str | None = None,
    ) -> None:
        # Handle clearing history first
        if clear:
            chan_id_clear: int = interaction.channel_id or 0
            if personality is not None and not await personas.visible(
                personality, interaction.user.id, self.bot
            ):
                await safe_send(
                    interaction,
                    "You are not allowed to use that persona.",
                    ephemeral=True,
                )
                return

            await self._history.clear(chan_id_clear, personality)
            target = f" for **{personality}**" if personality else ""
            await safe_send(
                interaction,
                f"Chat history{target} cleared.",
                ephemeral=True,
            )
            return

        # Select provider configured in settings
        provider_name: str = getattr(settings, "llm_provider", "gemini")
        try:
            provider = _providers.get(provider_name)
        except KeyError:
            await safe_send(
                interaction,
                f"LLM provider '{provider_name}' is not available.",
                ephemeral=True,
            )
            return

        if prompt is None:
            prompt = "Hello!"

        # Determine which personality prompt to use
        channel_id_int: int = int(
            (
                getattr(interaction, "channel_id", None)
                or (interaction.channel.id if interaction.channel else 0)
            )
            or 0
        )

        if personality is not None and await personas.visible(
            personality, interaction.user.id, self.bot
        ):
            # Explicit valid choice – remember it for this channel
            self._channel_persona[channel_id_int] = personality
        else:
            # Either no choice or invalid/stale choice – fall back
            # Fallback to default persona
            personality = self._channel_persona.get(channel_id_int, "Default")
            if personality not in personas.PERSONALITIES:
                personality = "Default"

        # Visibility check
        if not await personas.visible(personality, interaction.user.id, self.bot):
            await safe_send(interaction, "You are not allowed to use that persona.", ephemeral=True)
            return

        persona_prompt_str: str = personas.prompt(personality)

        final_system_prompt = DEFAULT_SYSTEM_PROMPT + "\n\n" + persona_prompt_str

        # Inform Discord we are processing (shows typing indicator)

        # Build chat history (excluding the system prompt – passed separately)
        messages: list[Message] = []
        for u, a in await self._history.recent(channel_id_int, personality):
            messages.append(Message(role="user", content=u))
            messages.append(Message(role="assistant", content=a))
        messages.append(Message(role="user", content=prompt))

        # Call the provider and collect its reply
        model_opt: str | None = getattr(settings, f"{provider_name}_model", None)
        try:
            raw_reply = await provider.generate(
                messages=messages,
                stream=True,
                model=model_opt or "",
                system_prompt=final_system_prompt,
            )
        except ModelOverloaded:
            await safe_send(
                interaction,
                "The language model is currently overloaded. Please try again in a moment.",
                ephemeral=True,
            )
            return
        except Exception as exc:
            # Don't expose internal errors to users
            await safe_send(
                interaction,
                "❌ Sorry, the language model encountered an error. Please try again.",
                ephemeral=True,
            )
            logger.exception(f"LLM provider error during generation: {exc}")
            return

        # Providers may still return an async iterator – normalise to a string
        if isinstance(raw_reply, str):
            response_text = raw_reply
        else:
            parts: list[str] = []
            try:
                async for fragment in raw_reply:
                    parts.append(fragment)
            except ModelOverloaded:
                await safe_send(
                    interaction,
                    "The language model is currently overloaded. Please try again in a moment.",
                    ephemeral=True,
                )
                return
            except Exception as exc:  # handle unforeseen provider errors mid-stream
                # Don't expose internal errors to users
                await safe_send(
                    interaction,
                    "❌ Sorry, the language model encountered an error during response. Please try again.",
                    ephemeral=True,
                )
                logger.exception(f"LLM provider error during streaming: {exc}")
                return
            response_text = "".join(parts)

        # Handle Discord's character limit by splitting into chunks
        if not response_text:
            await safe_send(interaction, "[No response]")
            return

        DISCORD_CHAR_LIMIT: int = DISCORD_LIMIT
        # Wrap response in Discord code blocks and chunk if necessary
        if len(response_text) + 10 <= DISCORD_CHAR_LIMIT:
            # Single-message response – simple code block
            await safe_send(interaction, f"```text\n{response_text}\n```", ephemeral=True)
        else:
            # Determine the maximum prefix length (e.g. "[Part 10/10]\n") so we can
            # make sure each chunk, plus its prefix *inside* the code-block fence, is
            # guaranteed to fit within Discord's hard limit (2000 characters).
            # We pessimistically assume two-digit indices – that is more than enough
            # for the 2000-char limit.
            # Reserve space for opening/closing code fences (`````text\n```) -> 10
            max_prefix_len: int = len(f"[Part {99}/{99}]\n")
            chunk_size: int = DISCORD_CHAR_LIMIT - 10 - max_prefix_len
            if chunk_size <= 0:
                # Fall-back safety – should never happen, but avoid ZeroDivisionError
                chunk_size = 50

            raw_chunks = [
                response_text[i : i + chunk_size] for i in range(0, len(response_text), chunk_size)
            ]
            total_parts = len(raw_chunks)
            for idx, chunk in enumerate(raw_chunks):
                part_prefix = f"[Part {idx + 1}/{total_parts}]\n" if total_parts > 1 else ""
                await safe_send(
                    interaction,
                    f"```text\n{part_prefix}{chunk}\n```",
                    ephemeral=True,
                )

        # Record the turn in history
        await self._history.record(channel_id_int, personality, (prompt or "", response_text))

    @chat.autocomplete("personality")
    async def personality_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        # Zero I/O fast path: compute visibility locally to meet Discord's ~3s autocomplete SLA.
        user_id: int = interaction.user.id
        owner_id: int | None = self.bot.owner_id if getattr(self.bot, "owner_id", None) else None

        names: list[str] = []
        for name in personas.PERSONALITIES.keys():
            if personas.visible_local(name, user_id, owner_id=owner_id):
                names.append(name)

        if current:
            lowered = current.lower()
            names = [n for n in names if lowered in n.lower()]

        return [app_commands.Choice(name=n.capitalize(), value=n) for n in names][:25]

    # ------------------------------------------------------------------
    # /chat round-table
    # ------------------------------------------------------------------
