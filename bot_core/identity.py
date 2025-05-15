from bot_core.settings import settings
import logging
log = logging.getLogger(__name__)

_DEFAULT_ROLE = "owner"

_role_map = settings.role_name_map

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

    # 2. Map Discord role names to bot roles via settings.role_name_map
    from bot_core.settings import settings
    for discord_role in getattr(user, 'roles', []):
        mapped = settings.role_name_map.get(discord_role.name)
        if mapped:
            return mapped

    # 3. Default to 'everyone'
    return "everyone"

def set_role(user_id: str, role: str):
    _role_map[str(user_id)] = role
