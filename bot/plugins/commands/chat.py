import discord
from discord import app_commands
from discord.ext import commands  # For commands.Bot, commands.Cog
from bot.core.settings import settings  # fully typed alias
from bot.personalities import PERSONALITIES, persona_prompt, persona_visible
from typing import Any, Optional as Opt, TYPE_CHECKING, cast
from bot.utils.history import ConversationHistory

if TYPE_CHECKING:
    from typing import (
        Any as GeminiContent,
        Any as GeminiPart,
        Any as GeminiGenerateContentConfig,
    )
    from google import genai

    # The following stubs shadow the google-genai types to avoid mypy errors.
    class types:
        Content = GeminiContent
        Part = GeminiPart
        GenerateContentConfig = GeminiGenerateContentConfig


INTERNAL_ERROR = "An internal error occurred. Please try again later."


# Static fallback list for autocomplete defaults
_ALL_CHOICES = [
    app_commands.Choice(name=k.capitalize(), value=k) for k in PERSONALITIES
]

# Global system instruction applied to every persona
DEFAULT_SYSTEM_PROMPT = "Always include your name at the beginning of a response."


class Chat(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()  # <-- no args
        self.bot = bot  # keep ref for future use
        self._client: "Opt[genai.Client]" = None
        # Remember last selected personality per channel
        self._channel_persona: dict[int, str] = {}
        # Rolling conversation history per channel & persona (tunable)
        self._history: ConversationHistory = ConversationHistory(
            max_turns=settings.conversation_max_turns
        )

    async def cog_unload(self) -> None:
        """Clean up resources when the cog is unloaded."""
        # Close the Gemini client if it exists
        if self._client is not None:
            # The Client doesn't have a close method, but we'll add this for future-proofing
            if hasattr(self._client, "close"):
                self._client.close()

    @app_commands.command(name="chat", description="Chat with Google Gemini")
    @app_commands.describe(
        prompt="What should I ask Gemini?", personality="Pick a persona"
    )
    async def chat(
        self,
        interaction: discord.Interaction,
        prompt: str | None = None,
        personality: str | None = None,
    ) -> None:
        GEMINI_API_KEY = settings.gemini_api_key
        if not GEMINI_API_KEY:
            await interaction.response.send_message(
                "GEMINI_API_KEY is not configured.", ephemeral=True
            )
            return None

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            await interaction.response.send_message(
                "google-genai package is not installed. Please run: pip install google-genai",
                ephemeral=True,
            )
            return None

        if prompt is None:
            prompt = "Hello!"

        # Determine which personality prompt to use
        chan_id: int = int(
            (
                getattr(interaction, "channel_id", None)
                or (interaction.channel.id if interaction.channel else 0)
            )
            or 0
        )

        if personality is not None:
            # Store explicit choice for this channel
            if chan_id is not None:
                self._channel_persona[chan_id] = personality
        else:
            # Fallback to last remembered choice
            personality = (
                self._channel_persona.get(chan_id, "default")
                if chan_id is not None
                else "default"
            )

        # Visibility check
        if not persona_visible(personality, interaction.user.id):
            await interaction.response.send_message(
                "You are not allowed to use that persona.", ephemeral=True
            )
            return

        persona_prompt_str: str = persona_prompt(personality)

        final_system_prompt = DEFAULT_SYSTEM_PROMPT + "\n\n" + persona_prompt_str

        try:
            self._client = genai.Client(api_key=GEMINI_API_KEY)
            model = settings.gemini_model

            # Build message history for Gemini using previously computed `chan_id`
            history_pairs = self._history.get(chan_id, personality)
            contents: list[types.Content] = []
            for user_msg, bot_msg in history_pairs:
                contents.append(
                    types.Content(
                        role="user", parts=[types.Part.from_text(text=user_msg)]
                    )
                )
                contents.append(
                    types.Content(
                        role="model", parts=[types.Part.from_text(text=bot_msg)]
                    )
                )

            # Append current turn
            contents.append(
                types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
            )

            generate_content_config = types.GenerateContentConfig(
                system_instruction=final_system_prompt,
                response_mime_type="text/plain",
            )
            # Stream and collect the response with handling to prevent blocking Discord's heartbeat
            response_text = ""
            stream = self._client.models.generate_content_stream(
                model=model,
                # list[Content] is too narrow for the parameter, cast to list[Any]
                contents=cast(list[Any], contents),
                config=generate_content_config,
            )

            # Add progress indicator for long-running responses
            await interaction.response.defer(thinking=True)
            progress_msg = cast(
                discord.Message, await interaction.followup.send("*Thinking...")
            )

            try:
                if hasattr(stream, "__aiter__"):  # real API
                    buffer = ""
                    last_update = (
                        0.0  # Changed to float to match time.time() return type
                    )
                    import time
                    import asyncio

                    async for chunk in stream:
                        text_fragment = getattr(chunk, "text", None)
                        if text_fragment:
                            buffer += text_fragment
                        # Yield control every 100ms to prevent heartbeat blocking
                        current_time = time.time()
                        if current_time - last_update >= 1.0:
                            # Update progress message every second to show activity
                            dots = "." * (int(current_time) % 4 + 1)
                            try:
                                # In tests, progress_msg might not have an edit method
                                if hasattr(progress_msg, "edit"):
                                    await progress_msg.edit(content=f"*Thinking{dots}*")
                            except Exception:
                                # Silently continue if edit fails
                                pass
                            last_update = current_time
                            # Yield control back to event loop
                            await asyncio.sleep(0.1)
                        response_text = buffer
                    # --- FINAL SYNC -------------------------------------------------
                    # Ensure we didn't miss the tail of the stream (<1 s since last update)
                    response_text = buffer
                else:  # the sync dummy used by tests
                    for chunk in stream:
                        text_fragment = getattr(chunk, "text", None)
                        if text_fragment:
                            response_text += text_fragment

                # Delete the progress message when done
                try:
                    # In tests, progress_msg might not have a delete method
                    if hasattr(progress_msg, "delete"):
                        await progress_msg.delete()
                except Exception:
                    # Silently continue if delete fails
                    pass
            except Exception as e:
                try:
                    # In tests, progress_msg might not have an edit method
                    if hasattr(progress_msg, "edit"):
                        await progress_msg.edit(
                            content=f"*Error while generating response: {e}*"
                        )
                except Exception:
                    # Fallback to a regular message if edit fails
                    await interaction.followup.send(
                        f"*Error while generating response: {e}*"
                    )
                raise

            # Handle Discord's 2000 character limit by splitting response into chunks
            if not response_text:
                await interaction.followup.send("[No response from Gemini]")
                return

            # Discord has a 2000 character limit
            DISCORD_CHAR_LIMIT = (
                settings.discord_chunk_size
            )  # Using 1900 to leave some margin

            # If response is within limit, send it as a single message
            if len(response_text) <= DISCORD_CHAR_LIMIT:
                await interaction.followup.send(response_text)
            else:
                # Split into multiple messages
                chunks = [
                    response_text[i : i + DISCORD_CHAR_LIMIT]
                    for i in range(0, len(response_text), DISCORD_CHAR_LIMIT)
                ]
                for i, chunk in enumerate(chunks):
                    # Add part number for multiple chunks
                    if len(chunks) > 1:
                        prefix = f"[Part {i + 1}/{len(chunks)}] "
                        # If adding prefix would exceed the limit, adjust the chunk
                        if len(prefix) + len(chunk) > DISCORD_CHAR_LIMIT:
                            chunk = chunk[: DISCORD_CHAR_LIMIT - len(prefix)]
                        chunk = prefix + chunk
                    await interaction.followup.send(chunk)

            # save to history
            self._history.record(chan_id, personality, prompt or "", response_text)
        except Exception as e:
            await interaction.followup.send(f"Gemini API error: {e}")

    # --------------------------- autocomplete ----------------------------

    @chat.autocomplete("personality")
    async def personality_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        visible = [
            app_commands.Choice(name=k.capitalize(), value=k)
            for k in PERSONALITIES
            if persona_visible(k, interaction.user.id)
        ]
        if not current:
            return visible[:25]
        lowered = current.lower()
        return [c for c in visible if lowered in c.name.lower()][:25]

    # ------------------------------------------------------------------
    # /chat round-table
    # ------------------------------------------------------------------

    @app_commands.command(
        name="roundtable",
        description="Ask the same question to every available persona.",
    )
    @app_commands.describe(prompt="What should I ask Gemini?")
    async def round_table(
        self,
        interaction: discord.Interaction,
        prompt: str | None = None,
    ) -> None:
        """Send the prompt to *all* personas and stream their replies."""

        if prompt is None:
            prompt = "Hello!"

        GEMINI_API_KEY = settings.gemini_api_key
        if not GEMINI_API_KEY:
            await interaction.response.send_message(
                "GEMINI_API_KEY is not configured.", ephemeral=True
            )
            return None

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            await interaction.response.send_message(
                "google-genai package is not installed. Please run: pip install google-genai",
                ephemeral=True,
            )
            return None

        import asyncio

        await interaction.response.defer(thinking=True)

        async def _ask_persona(
            name: str, persona_prompt: str
        ) -> tuple[str, str | None, Exception | None]:
            """Run blocking Gemini calls in a thread to avoid event-loop stalls."""

            def _sync_call() -> str:
                client = genai.Client(api_key=GEMINI_API_KEY)
                # Build conversation history for this channel & persona
                chan_id: int = interaction.channel_id or 0
                history_pairs = self._history.get(chan_id, name)
                contents: list[types.Content] = []
                for user_msg, bot_msg in history_pairs:
                    contents.append(
                        types.Content(
                            role="user", parts=[types.Part.from_text(text=user_msg)]
                        )
                    )
                    contents.append(
                        types.Content(
                            role="model", parts=[types.Part.from_text(text=bot_msg)]
                        )
                    )

                # Append current user prompt
                contents.append(
                    types.Content(
                        role="user", parts=[types.Part.from_text(text=prompt)]
                    )
                )
                config = types.GenerateContentConfig(
                    system_instruction=DEFAULT_SYSTEM_PROMPT + "\n\n" + persona_prompt,
                    response_mime_type="text/plain",
                )
                stream = client.models.generate_content_stream(
                    model=settings.gemini_model,
                    # list[Content] is too narrow for the parameter, cast to list[Any]
                    contents=cast(list[Any], contents),
                    config=config,
                )

                text_accum = ""
                # google-genai stream may be sync iterable; iterate normally.
                for chunk in stream:
                    text_fragment = getattr(chunk, "text", None)
                    if text_fragment:
                        text_accum += text_fragment
                return text_accum or "[No response]"

            try:
                response_text: str = await asyncio.to_thread(_sync_call)
                return (name, response_text, None)
            except Exception as exc:  # pragma: no cover
                return (name, None, exc)

        # launch tasks only for visible personas
        visible_items = [
            (n, p["prompt"])
            for n, p in PERSONALITIES.items()
            if persona_visible(n, interaction.user.id)
        ]
        if not visible_items:
            await interaction.response.send_message(
                "No personas available.", ephemeral=True
            )
            return

        tasks = [
            asyncio.create_task(_ask_persona(n, prompt_str))
            for n, prompt_str in visible_items
        ]

        for coro in asyncio.as_completed(tasks):
            name, text, err = await coro

            # Convert Optional[str] -> str for static typing safety
            safe_text: str = text or ""

            title = f"**{name.capitalize()}**"
            if err is not None:
                await interaction.followup.send(
                    f"{title} (error): {err}", ephemeral=True
                )
                continue

            # Discord limit handling (2000 chars). Wrap each chunk in its own code block.
            DISCORD_CHAR_LIMIT = settings.discord_chunk_size  # margin for title/prefix

            if len(safe_text) + len(title) + 10 <= DISCORD_CHAR_LIMIT:
                await interaction.followup.send(f"{title}\n```text\n{safe_text}\n```")
            else:
                raw_chunks = [
                    safe_text[
                        i : i + DISCORD_CHAR_LIMIT - 10
                    ]  # 10 for code fences and margin
                    for i in range(0, len(safe_text), DISCORD_CHAR_LIMIT - 10)
                ]
                for idx, chunk in enumerate(raw_chunks):
                    part_prefix = (
                        f"{title} [Part {idx + 1}/{len(raw_chunks)}]\n"
                        if len(raw_chunks) > 1
                        else f"{title}\n"
                    )
                    await interaction.followup.send(
                        part_prefix + f"```text\n{chunk}\n```"
                    )

            # record turn in history
            chan_id: int = interaction.channel_id or 0
            self._history.record(chan_id, name, prompt or "", safe_text)

    # ------------------------------------------------------------------
    # /chat round-table
    # ------------------------------------------------------------------


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Chat(bot))
