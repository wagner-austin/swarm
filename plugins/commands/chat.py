from plugins.manager import plugin
from core.permissions import EVERYONE
from core.config import OPENAI_API_KEY

@plugin(commands=["chat"], canonical="chat", required_role=EVERYONE)
async def run_command(args: str, ctx, state_machine, **kwargs):
    if not OPENAI_API_KEY:
        return "OPENAI_API_KEY is not configured."

    prompt = args.strip() or "Hello!"
    from openai import AsyncOpenAI
    client = AsyncOpenAI()
    rsp = await client.chat.completions.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
    )
    return rsp.choices[0].message.content
