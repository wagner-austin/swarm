from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from discord.ext import commands

from swarm.ai import personas as p
from swarm.history.in_memory import MemoryBackend
from swarm.plugins.commands.chat import Chat


@pytest.fixture(autouse=True)
def restore_personas() -> None:
    original = dict(p.PERSONALITIES)
    yield
    p.PERSONALITIES.clear()
    p.PERSONALITIES.update(original)


def _mk_interaction(user_id: int):
    inter = MagicMock()
    user = MagicMock()
    user.id = user_id
    inter.user = user
    return inter


@pytest.mark.asyncio
async def test_personality_autocomplete_filters_public_and_user_and_owner() -> None:
    # Setup personas
    p.PERSONALITIES.clear()
    p.PERSONALITIES.update(
        {
            "public": {"prompt": "p", "allowed_users": None},
            "useronly": {"prompt": "u", "allowed_users": [1234]},
            "owneronly": {"prompt": "o", "allowed_users": ["${OWNER_ID}"]},
        }
    )

    # Bot stub with an owner id
    bot = MagicMock(spec=commands.Bot)
    bot.owner_id = 9999

    chat = Chat(discord_bot=bot, history_backend=MemoryBackend(max_turns=1))

    # Case 1: ordinary user (not owner, not in user list)
    inter = _mk_interaction(user_id=5555)
    choices = await chat.personality_autocomplete(interaction=inter, current="")
    got = {(c.name, c.value) for c in choices}
    assert ("Public", "public") in got
    assert ("Useronly", "useronly") not in got
    assert ("Owneronly", "owneronly") not in got

    # Case 2: allowed user
    inter_user = _mk_interaction(user_id=1234)
    choices_user = await chat.personality_autocomplete(interaction=inter_user, current="")
    got_user = {(c.name, c.value) for c in choices_user}
    assert ("Public", "public") in got_user
    assert ("Useronly", "useronly") in got_user
    assert ("Owneronly", "owneronly") not in got_user

    # Case 3: owner
    inter_owner = _mk_interaction(user_id=9999)
    choices_owner = await chat.personality_autocomplete(interaction=inter_owner, current="")
    got_owner = {(c.name, c.value) for c in choices_owner}
    assert ("Public", "public") in got_owner
    assert ("Owneronly", "owneronly") in got_owner


@pytest.mark.asyncio
async def test_personality_autocomplete_search_filter() -> None:
    p.PERSONALITIES.clear()
    p.PERSONALITIES.update(
        {
            "public": {"prompt": "p", "allowed_users": None},
            "pirate": {"prompt": "arrr", "allowed_users": None},
        }
    )
    bot = MagicMock(spec=commands.Bot)
    bot.owner_id = None
    chat = Chat(discord_bot=bot, history_backend=MemoryBackend(max_turns=1))

    inter = _mk_interaction(user_id=1)
    choices = await chat.personality_autocomplete(interaction=inter, current="pir")
    got_vals = [c.value for c in choices]
    assert "pirate" in got_vals
    assert "public" not in got_vals
