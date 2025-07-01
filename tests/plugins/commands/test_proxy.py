from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from pytest_mock import MockerFixture

from bot.netproxy.service import ProxyService
from bot.plugins.commands.proxy import ProxyCog


@pytest.fixture
def mock_proxy_service() -> MagicMock:
    svc = MagicMock(spec=ProxyService)
    svc.start = AsyncMock()
    svc.stop = AsyncMock()
    svc.describe = MagicMock(return_value="Proxy running on 127.0.0.1:9000")
    svc.in_q = MagicMock()
    svc.in_q.qsize.return_value = 3
    svc.in_q.maxsize = 10
    svc.out_q = MagicMock()
    svc.out_q.qsize.return_value = 2
    svc.out_q.maxsize = 10
    return svc


@pytest.fixture
def dummy_bot() -> MagicMock:
    bot = MagicMock(spec=discord.ext.commands.Bot)
    bot.container = MagicMock()  # Patch in a dummy DI container
    return bot


@pytest.fixture
def interaction() -> MagicMock:
    inter = MagicMock(spec=discord.Interaction)
    inter.response = MagicMock()
    inter.response.defer = AsyncMock()
    inter.followup = MagicMock()
    inter.followup.send = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_start_command(
    dummy_bot: MagicMock,
    mock_proxy_service: MagicMock,
    interaction: MagicMock,
    mocker: MockerFixture,
) -> None:
    mock_safe_send = mocker.patch("bot.plugins.commands.proxy.safe_send", new_callable=AsyncMock)
    mock_safe_defer = mocker.patch("bot.plugins.commands.proxy.safe_defer", new_callable=AsyncMock)
    cog = ProxyCog(dummy_bot, proxy_service=mock_proxy_service)

    await cog._start_impl(interaction)
    mock_safe_defer.assert_awaited_once_with(interaction, thinking=True, ephemeral=True)
    mock_proxy_service.start.assert_awaited_once()
    mock_safe_send.assert_awaited_once_with(interaction, "Proxy running on 127.0.0.1:9000")


@pytest.mark.asyncio
async def test_stop_command(
    dummy_bot: MagicMock,
    mock_proxy_service: MagicMock,
    interaction: MagicMock,
    mocker: MockerFixture,
) -> None:
    mock_safe_send = mocker.patch("bot.plugins.commands.proxy.safe_send", new_callable=AsyncMock)
    mock_safe_defer = mocker.patch("bot.plugins.commands.proxy.safe_defer", new_callable=AsyncMock)
    cog = ProxyCog(dummy_bot, proxy_service=mock_proxy_service)

    await cog._stop_impl(interaction)
    mock_safe_defer.assert_awaited_once_with(interaction, thinking=True, ephemeral=True)
    mock_proxy_service.stop.assert_awaited_once()
    mock_safe_send.assert_awaited_once_with(interaction, "🛑 Proxy stopped.")


@pytest.mark.asyncio
async def test_status_command(
    dummy_bot: MagicMock,
    mock_proxy_service: MagicMock,
    interaction: MagicMock,
    mocker: MockerFixture,
) -> None:
    mock_safe_send = mocker.patch("bot.plugins.commands.proxy.safe_send", new_callable=AsyncMock)
    mock_safe_defer = mocker.patch("bot.plugins.commands.proxy.safe_defer", new_callable=AsyncMock)
    cog = ProxyCog(dummy_bot, proxy_service=mock_proxy_service)

    await cog._status_impl(interaction)
    mock_safe_defer.assert_awaited_once_with(interaction, thinking=True, ephemeral=True)
    mock_proxy_service.describe.assert_called_once()
    expected_status = "Proxy running on 127.0.0.1:9000\n📥 in-queue 3/10  📤 out-queue 2/10"
    mock_safe_send.assert_awaited_once_with(interaction, expected_status)
