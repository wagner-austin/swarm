import json
import os
import logging
log = logging.getLogger(__name__)

_DEFAULT_ROLE = "owner"

# env EXAMPLE: BOT_ROLES='{"123456789012345678":"owner","987…":"admin"}'
_role_map = json.loads(os.getenv("BOT_ROLES", "{}"))

def resolve_role(user: 'discord.Member') -> str:
    """
    Resolve the role of a given Discord member.

    The role is determined in the following order:
    1. Explicit BOT_ROLES override by user ID.
    2. Mapping of Discord role names to bot roles via ROLE_NAME_MAP.
    3. Default to 'everyone'.

    Args:
        user (discord.Member): The Discord member to resolve the role for.

    Returns:
        str: The resolved role.
    """
    # 0. Accept plain strings / ints as well as discord.* objects
    try:
        user_id = str(user.id)           # discord.Member / discord.User etc.
    except AttributeError:
        user_id = str(user)              # fallback – already a string/int

    # 1. Check explicit BOT_ROLES override
    role = _role_map.get(user_id)
    if role:
        return role

    # 2. Map Discord role names to bot roles via ROLE_NAME_MAP
    from bot_core.config import ROLE_NAME_MAP
    for discord_role in getattr(user, 'roles', []):
        mapped = ROLE_NAME_MAP.get(discord_role.name)
        if mapped:
            return mapped

    # 3. Default to 'everyone'
    return "everyone"

def set_role(user_id: str, role: str):
    _role_map[str(user_id)] = role
