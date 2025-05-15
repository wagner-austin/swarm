from plugins.manager import plugin
from core.permissions import EVERYONE
import os

# Requires: pip install google-genai

@plugin(commands=["chat"], canonical="chat", required_role=EVERYONE)
async def run_command(args: str, ctx, state_machine, **kwargs):
    # Use Gemini API for chat
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return "google-genai package is not installed. Please run: pip install google-genai"

    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        return "GEMINI_API_KEY is not configured."

    prompt = args.strip() or "Hello!"
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
        return response_text or "[No response from Gemini]"
    except Exception as e:
        return f"Gemini API error: {e}"
