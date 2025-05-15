def extract_user_id(ctx) -> str | None:
    """
    Return a stable string identifier from either a discord.Message,
    a discord.Member, or the legacy Signal envelope.
    """
    if hasattr(ctx, "author") and hasattr(ctx.author, "id"):
        return str(ctx.author.id)
    if hasattr(ctx, "id"):          # discord.Member
        return str(ctx.id)
    return str(getattr(ctx, "sender", None))
