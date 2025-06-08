# tests/proxy/test_port_already_in_use.py
from __future__ import annotations

import pytest
from bot.infra.tankpit.proxy.service import ProxyService


@pytest.mark.asyncio
async def test_port_in_use_raises_clean_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.infra.tankpit.proxy.service.ProxyService._is_port_free",
        staticmethod(lambda *_: False),  # *all* candidate ports busy
    )
    svc = ProxyService(port=9000)
    with pytest.raises(RuntimeError, match="No free port"):
        await svc.start()
