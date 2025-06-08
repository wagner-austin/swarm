# File: tests/test_startup_smoke.py


import pytest
from typing import Any

# ── internal entry-points we want to exercise ─────────────────────────
from bot.core.discord_runner import run_bot


@pytest.mark.asyncio
async def test_bot_startup_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Boots the full discord-runner stack, but with every external side-effect
    (Discord API, mitmproxy, Chrome) stubbed out so the coroutine returns
    immediately.  The goal is to detect regressions in the startup path
    (import cycles, bad awaits, missing attrs) without hitting the network.
    """

    # ------------------------------------------------------------------
    # 1.  Guarantee a valid token in the already-imported settings singleton
    # ------------------------------------------------------------------
    monkeypatch.setattr(
        "bot.core.settings.settings.discord_token", "stub-token", raising=False
    )

    # ------------------------------------------------------------------
    # 2.  Stub discord.ext.commands.Bot.start/close so we don’t touch Discord
    # ------------------------------------------------------------------
    async def fake_bot_start(
        self: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:  # noqa: D401
        # Immediately drop back into the caller the same way a Ctrl-C would,
        # which run_bot already handles gracefully.
        raise KeyboardInterrupt

    async def fake_bot_close(self: Any) -> None:  # noqa: D401
        return None

    monkeypatch.setattr("discord.ext.commands.Bot.start", fake_bot_start, raising=True)
    monkeypatch.setattr("discord.ext.commands.Bot.close", fake_bot_close, raising=True)
    monkeypatch.setattr(
        "discord.ext.commands.Bot.is_closed", lambda self: True, raising=False
    )

    # ------------------------------------------------------------------
    # 3.  Stub the TankPit ProxyService so no mitmproxy subprocess kicks off
    # ------------------------------------------------------------------
    async def fake_proxy_start(self: Any) -> str:  # noqa: D401
        return "proxy-started"

    async def fake_proxy_stop(self: Any) -> str:  # noqa: D401
        return "proxy-stopped"

    from bot.infra.tankpit.proxy.service import ProxyService

    monkeypatch.setattr(ProxyService, "start", fake_proxy_start, raising=False)
    monkeypatch.setattr(ProxyService, "stop", fake_proxy_stop, raising=False)

    # ------------------------------------------------------------------
    # 4.  Finally exercise the runner.  If any step raises, pytest will fail.
    # ------------------------------------------------------------------
    svc = ProxyService(port=9999)
    await run_bot(svc)
