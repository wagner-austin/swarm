from discord.ext import commands
from bot_core.settings import settings  # fully typed alias
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from typing import (
        Any as GeminiContent,
        Any as GeminiPart,
        Any as GeminiGenerateContentConfig,
    )

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
        for cmd in self.get_commands():
            cmd.cog = self

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
            client = genai.Client(api_key=GEMINI_API_KEY)
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
            # Stream and collect the response – works for both async *and* sync generators
            response_text = ""
            stream = client.models.generate_content_stream(
                model=model,
                contents=contents,  # type: ignore[arg-type]
                config=generate_content_config,
            )
            if hasattr(stream, "__aiter__"):  # real API
                async for chunk in stream:
                    response_text += getattr(chunk, "text", "")
            else:  # the sync dummy used by tests
                for chunk in stream:
                    response_text += getattr(chunk, "text", "")
            await ctx.send(response_text or "[No response from Gemini]")
        except Exception as e:
            await ctx.send(f"Gemini API error: {e}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Chat(bot))
