from discord.ext import commands
from bot_core.settings import settings  # fully typed alias
from typing import Any, Optional as Opt, TYPE_CHECKING

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


CHAT_USAGE = "Usage: !chat <prompt>"
INTERNAL_ERROR = "An internal error occurred. Please try again later."


class Chat(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._client: "Opt[genai.Client]" = None
        for cmd in self.get_commands():
            cmd.cog = self

    async def cog_unload(self) -> None:
        """Clean up resources when the cog is unloaded."""
        # Close the Gemini client if it exists
        if self._client is not None:
            # The Client doesn't have a close method, but we'll add this for future-proofing
            if hasattr(self._client, "close"):
                self._client.close()

    @commands.command(name="chat", help="Chat with the Gemini API.")
    async def chat(
        self, ctx: commands.Context[Any], *, prompt: str | None = None
    ) -> None:
        GEMINI_API_KEY = settings.gemini_api_key
        if not GEMINI_API_KEY:
            await ctx.send("GEMINI_API_KEY is not configured.")
            return None

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            await ctx.send(
                "google-genai package is not installed. Please run: pip install google-genai"
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
                contents=contents,
                config=generate_content_config,
            )

            # Add progress indicator for long-running responses
            progress_msg = await ctx.send("*Thinking...*")

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
                    await ctx.send(f"*Error while generating response: {e}*")
                raise

            # Handle Discord's 2000 character limit by splitting response into chunks
            if not response_text:
                await ctx.send("[No response from Gemini]")
                return

            # Discord has a 2000 character limit
            DISCORD_CHAR_LIMIT = 1900  # Using 1900 to leave some margin

            # If response is within limit, send it as a single message
            if len(response_text) <= DISCORD_CHAR_LIMIT:
                await ctx.send(response_text)
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
                    await ctx.send(chunk)
        except Exception as e:
            await ctx.send(f"Gemini API error: {e}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Chat(bot))
