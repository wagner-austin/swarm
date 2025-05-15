from discord.ext import commands, tasks
import importlib

class Extensions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="load")
    @commands.is_owner()
    async def load_(self, ctx, module: str):
        await ctx.bot.load_extension(module)
        await ctx.send(f"Loaded `{module}`")

    @commands.command(name="unload")
    @commands.is_owner()
    async def unload_(self, ctx, module: str):
        await ctx.bot.unload_extension(module)
        await ctx.send(f"Unloaded `{module}`")

    @commands.command(name="reload")
    @commands.is_owner()
    async def reload_(self, ctx, module: str):
        await ctx.bot.unload_extension(module)
        await ctx.bot.load_extension(module)
        await ctx.send(f"Reloaded `{module}`")

async def setup(bot):
    await bot.add_cog(Extensions(bot))
