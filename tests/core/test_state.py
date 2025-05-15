"""
tests/core/test_state.py - Tests for the bot state management.
"""

from bot_core.state import BotStateMachine

import pytest
@pytest.mark.asyncio
async def test_state_machine_initially_running():
    state_machine = BotStateMachine()
    assert state_machine.should_continue() is True

@pytest.mark.asyncio
async def test_state_machine_shutdown():
    state_machine = BotStateMachine()
    state_machine.shutdown()
    assert state_machine.should_continue() is False

# End of tests/core/test_state.py