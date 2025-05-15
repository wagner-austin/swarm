from discord.ext import commands
from bot_core.settings import settings

CHAT_USAGE = "Usage: !chat <prompt>"
INTERNAL_ERROR = "An internal error occurred. Please try again later."

class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="chat", help="Chat with the Gemini API.")
    async def chat(self, ctx, *, prompt: str = "Hello!"):
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            await ctx.send("google-genai package is not installed. Please run: pip install google-genai")
            return

        GEMINI_API_KEY = settings.gemini_api_key
        if not GEMINI_API_KEY:
            await ctx.send("GEMINI_API_KEY is not configured.")
            return

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
            # Stream and collect the response
            response_text = ""
            async for chunk in client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=generate_content_config,
            ):
                response_text += getattr(chunk, "text", "")
            await ctx.send(response_text or "[No response from Gemini]")
        except Exception as e:
            await ctx.send(f"Gemini API error: {e}")

async def setup(bot):
    await bot.add_cog(Chat(bot))
