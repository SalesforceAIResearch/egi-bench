"""Tests for mcpuniverse.rl.dispatcher module."""

import pytest

from mcpuniverse.rl.dispatcher import get_dispatcher, DISPATCHER_REGISTRY


class TestDispatcherRegistry:
    """Tests for dispatcher registry."""

    def test_registry_has_all_types(self):
        assert "async_pipeline" in DISPATCHER_REGISTRY
        assert "async_batch" in DISPATCHER_REGISTRY
        assert "sequential" in DISPATCHER_REGISTRY

    def test_get_async_pipeline(self):
        d = get_dispatcher("async_pipeline")
        assert callable(d)

    def test_get_async_batch(self):
        d = get_dispatcher("async_batch")
        assert callable(d)

    def test_get_sequential(self):
        d = get_dispatcher("sequential")
        assert callable(d)

    def test_unknown_dispatcher_raises(self):
        with pytest.raises((KeyError, ValueError)):
            get_dispatcher("nonexistent_dispatcher")

    def test_dispatchers_are_coroutines(self):
        """All dispatchers should be async functions."""
        import asyncio

        for name in ["async_pipeline", "async_batch", "sequential"]:
            d = get_dispatcher(name)
            assert asyncio.iscoroutinefunction(d), (
                f"Dispatcher '{name}' should be an async function"
            )

    def test_registry_count(self):
        assert len(DISPATCHER_REGISTRY) >= 3
