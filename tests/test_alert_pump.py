"""Integration-style test for alert queue → DM relay via AlertPump.

Relies only on pytest-asyncio (already in dev deps) and built-in monkeypatch.
No live Discord connection is made; a dummy Bot/Owner pair is stubbed.
"""

from __future__ import annotations

import asyncio
import types
from typing import Any, Optional

import pytest

from bot.core.lifecycle import BotLifecycle
from bot.core.settings import Settings
from bot.core import alerts as alert_mod
from bot.plugins.commands.alert_pump import AlertPump


@pytest.mark.asyncio
async def test_alert_reaches_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure that a message placed on lifecycle.alerts_q is delivered via AlertPump."""

    # ------------------------------------------------------------------
    # 1. Fake Discord objects with minimal API surface the cog expects
    # ------------------------------------------------------------------
    class _DummyOwner:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, msg: str) -> None:  # noqa: D401 – discord.py API mimic
            self.sent.append(msg)

    owner = _DummyOwner()

    class _DummyBot:  # noqa: D101 – test helper
        owner_id = 42

        def __init__(self, lifecycle: BotLifecycle) -> None:
            self._lifecycle = lifecycle
            self._cogs: dict[str, object] = {}

        # Attributes / helpers consumed by AlertPump -------------------
        @property
        def lifecycle(self) -> BotLifecycle:  # noqa: D401 – property style mimics production
            return self._lifecycle

        def get_user(self, uid: int) -> Optional[_DummyOwner]:  # noqa: D401 – simple stub
            return owner if uid == self.owner_id else None

        async def application_info(self) -> types.SimpleNamespace:  # noqa: D401 – returns dummy app info
            return types.SimpleNamespace(owner=owner)

        # Discord.py machinery stubs -----------------------------------
        def add_listener(
            self, *_a: object, **_kw: object
        ) -> None:  # not used by the cog
            pass

        def add_cog(self, cog: Any) -> None:  # noqa: D401 – emulate Cog addition
            key: str = getattr(cog, "qualified_name", cog.__class__.__name__)
            self._cogs[key] = cog

        def remove_cog(self, name: str) -> None:  # noqa: D401
            self._cogs.pop(name, None)

        def is_closed(self) -> bool:  # noqa: D401 – used by relay loop exit check
            return False

    # ------------------------------------------------------------------
    # 2. Real BotLifecycle instance with dummy settings token
    # ------------------------------------------------------------------
    lifecycle = BotLifecycle(Settings(discord_token="dummy-token"))
    bot: _DummyBot = _DummyBot(lifecycle)

    # ------------------------------------------------------------------
    # 3. Load the AlertPump cog (invoke cog_load manually)
    # ------------------------------------------------------------------
    pump = AlertPump(bot)  # type: ignore[arg-type]
    await pump.cog_load()

    # ------------------------------------------------------------------
    # 4. Expose lifecycle singleton and emit alert
    # ------------------------------------------------------------------
    from bot.core import (
        lifecycle as lc_mod,
    )  # import inside function to avoid early side effects

    lc_mod._lifecycle_singleton = lifecycle

    alert_mod.alert("integration-test-alert")

    # ------------------------------------------------------------------
    # 5. Allow event-loop a moment to process the queue
    # ------------------------------------------------------------------
    await asyncio.sleep(0.05)  # single loop-tick usually suffices

    # ------------------------------------------------------------------
    # 6. Assertions and cleanup
    # ------------------------------------------------------------------
    assert owner.sent == ["⚠️ **Bot alert:** integration-test-alert"]

    await pump.cog_unload()
