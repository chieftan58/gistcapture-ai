"""Quick test to verify test infrastructure is working"""

import pytest


def test_pytest_is_working():
    """Verify pytest runs"""
    assert True


@pytest.mark.unit
def test_markers_work():
    """Verify test markers work"""
    assert 1 + 1 == 2


@pytest.mark.asyncio
async def test_async_support():
    """Verify async tests work"""
    import asyncio
    await asyncio.sleep(0.01)
    assert True