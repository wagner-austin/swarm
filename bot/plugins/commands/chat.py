import discord
from discord import app_commands
from discord.ext import commands  # For commands.Bot, commands.Cog
from bot.core.settings import settings  # fully typed alias
from typing import Any, Optional as Opt, TYPE_CHECKING, cast

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


class Chat(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()  # <-- no args
        self.bot = bot  # keep ref for future use
        self._client: "Opt[genai.Client]" = None

    async def cog_unload(self) -> None:
        """Clean up resources when the cog is unloaded."""
        # Close the Gemini client if it exists
        if self._client is not None:
            # The Client doesn't have a close method, but we'll add this for future-proofing
            if hasattr(self._client, "close"):
                self._client.close()

    @app_commands.command(name="chat", description="Chat with Google Gemini")
    @app_commands.describe(prompt="What should I ask Gemini?")
    async def chat(
        self, interaction: discord.Interaction, prompt: str | None = None
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

        try:
            self._client = genai.Client(api_key=GEMINI_API_KEY)
            model = "gemini-2.5-flash-preview-04-17"
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=prompt)],
                ),
            ]
            generate_content_config = types.GenerateContentConfig(
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
                        buffer += getattr(chunk, "text", "")
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
                else:  # the sync dummy used by tests
                    for chunk in stream:
                        response_text += getattr(chunk, "text", "")

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
            DISCORD_CHAR_LIMIT = 1900  # Using 1900 to leave some margin

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
        except Exception as e:
            await interaction.followup.send(f"Gemini API error: {e}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Chat(bot))
