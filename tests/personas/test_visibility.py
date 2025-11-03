from __future__ import annotations

import importlib

import pytest

from swarm.ai import personas as p


@pytest.fixture(autouse=True)
def restore_personas() -> None:
    original = dict(p.PERSONALITIES)
    yield
    p.PERSONALITIES.clear()
    p.PERSONALITIES.update(original)
    importlib.reload(p)


def test_visible_local_public_persona() -> None:
    p.PERSONALITIES.update({"public": {"prompt": "x", "allowed_users": None}})
    assert p.visible_local("public", user_id=1, owner_id=None) is True
    assert p.visible_local("public", user_id=999, owner_id=123) is True


def test_visible_local_specific_user_allowed() -> None:
    p.PERSONALITIES.update({"vip": {"prompt": "x", "allowed_users": [42, "1001"]}})
    assert p.visible_local("vip", user_id=42, owner_id=None) is True
    assert p.visible_local("vip", user_id=1001, owner_id=None) is True
    assert p.visible_local("vip", user_id=7, owner_id=None) is False


def test_visible_local_owner_token() -> None:
    p.PERSONALITIES.update({"owneronly": {"prompt": "x", "allowed_users": ["${OWNER_ID}"]}})
    assert p.visible_local("owneronly", user_id=999, owner_id=None) is False
    assert p.visible_local("owneronly", user_id=999, owner_id=999) is True
    assert p.visible_local("owneronly", user_id=1000, owner_id=999) is False
