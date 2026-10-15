"""
Integration tests for env_pool against a real Docker daemon.

These tests create real Docker containers via DockerProvisioner and
EnvPoolManager.  They are skipped automatically when the required
environment variables are not set.

Environment variables:
    CPU_POD_DOCKER_HOST    Docker API endpoint (e.g. tcp://<host>:2375).
    CPU_POD_HOST           Hostname/IP that containers are reachable at
                           (default: localhost).
    CPU_POD_DOCKER_HOST_2  Second Docker host for multi-pod tests.
    CPU_POD_HOST_2         Hostname/IP for the second pod.
    FAST_CLEANUP           Set to "true" to reset (not destroy) containers
                           between tests for faster iteration.

Usage (single pod):
    export CPU_POD_DOCKER_HOST="tcp://<docker-host>:2375"
    export CPU_POD_HOST="<reachable-ip>"
    python -m pytest tests/mcp/env_pool/test_env_pool.py -v -s

Usage (multi-pod):
    export CPU_POD_DOCKER_HOST="tcp://<docker-host-1>:2375"
    export CPU_POD_HOST="<reachable-ip-1>"
    export CPU_POD_DOCKER_HOST_2="tcp://<docker-host-2>:2375"
    export CPU_POD_HOST_2="<reachable-ip-2>"
    python -m pytest tests/mcp/env_pool/test_env_pool.py -v -s
"""

import os
import time
import unittest
from pathlib import Path
from typing import List

from mcpuniverse.mcp.env_pool import (
    DockerProvisioner,
    EnvConfig,
    EnvInfo,
    EnvPoolManager,
    EnvStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[2]  # tests/mcp/env_pool -> project root
_DOCKERFILE = _TEST_DIR / "Dockerfile.test"

DOCKER_HOST = os.getenv("CPU_POD_DOCKER_HOST")
GATEWAY_HOST = os.getenv("CPU_POD_HOST", "localhost")
DOCKER_HOST_2 = os.getenv("CPU_POD_DOCKER_HOST_2")
GATEWAY_HOST_2 = os.getenv("CPU_POD_HOST_2", "localhost")
FAST_CLEANUP = os.getenv("FAST_CLEANUP", "false").lower() == "true"


def _make_config(**overrides) -> EnvConfig:
    """Return a lightweight EnvConfig for testing."""
    defaults = dict(
        dockerfile_path=str(_DOCKERFILE),
        servers=[],
        cpu_limit="1",
        memory_limit="2g",
    )
    defaults.update(overrides)
    return EnvConfig(**defaults)


def _unique_id(prefix: str = "test") -> str:
    return f"{prefix}-{int(time.time())}"


# ---------------------------------------------------------------------------
# Base class — shared provisioner setup & teardown
# ---------------------------------------------------------------------------

@unittest.skipUnless(DOCKER_HOST, "CPU_POD_DOCKER_HOST not set")
@unittest.skipUnless(_DOCKERFILE.exists(), f"{_DOCKERFILE} not found")
class _DockerTestBase(unittest.IsolatedAsyncioTestCase):
    """Shared setup for all integration test classes."""

    provisioner: DockerProvisioner

    def setUp(self):
        self.provisioner = DockerProvisioner(
            docker_host=DOCKER_HOST,
            host=GATEWAY_HOST,
            base_port=9000,
            startup_timeout=180.0,
            build_context=str(_PROJECT_ROOT),
            auto_build=True,
            image_prefix="mcp-universe/test-gateway",
        )

    async def asyncTearDown(self):
        try:
            if FAST_CLEANUP:
                await self.provisioner.reset_all()
            else:
                await self.provisioner.cleanup_all()
        except Exception:
            pass  # best-effort cleanup


# ---------------------------------------------------------------------------
# DockerProvisioner tests
# ---------------------------------------------------------------------------

class TestDockerProvisioner(_DockerTestBase):

    async def test_docker_connection(self):
        """Verify basic connectivity to the Docker daemon."""
        result = await self.provisioner.list_all()
        self.assertIsInstance(result, list)

    async def test_create_single_env(self):
        """Create one container and verify it reaches READY."""
        config = _make_config()
        env_id = _unique_id("single")

        env = await self.provisioner.create(env_id, config=config)

        self.assertEqual(env.env_id, env_id)
        self.assertEqual(env.status, EnvStatus.READY)
        self.assertIsNotNone(env.container_id)
        self.assertTrue(env.gateway_address.startswith("http://"))

    async def test_create_multiple_envs(self):
        """Create several containers with distinct ports."""
        config = _make_config()
        ids = [_unique_id(f"multi-{i}") for i in range(3)]

        envs: List[EnvInfo] = []
        for eid in ids:
            envs.append(await self.provisioner.create(eid, config=config))

        addresses = {e.gateway_address for e in envs}
        self.assertEqual(len(addresses), 3, "each env should have a unique address")
        for env in envs:
            self.assertEqual(env.status, EnvStatus.READY)

    async def test_health_check(self):
        """Health check returns True for a running container."""
        config = _make_config()
        env_id = _unique_id("health")
        await self.provisioner.create(env_id, config=config)

        self.assertTrue(await self.provisioner.health_check(env_id))

    async def test_reset_env(self):
        """Reset restarts the container and it becomes READY again."""
        config = _make_config()
        env_id = _unique_id("reset")
        await self.provisioner.create(env_id, config=config)

        self.assertTrue(await self.provisioner.reset(env_id))

        info = await self.provisioner.get_info(env_id)
        self.assertEqual(info.status, EnvStatus.READY)

    async def test_destroy_env(self):
        """Destroy removes the container."""
        config = _make_config()
        env_id = _unique_id("destroy")
        await self.provisioner.create(env_id, config=config)

        self.assertTrue(await self.provisioner.destroy(env_id))

        # destroy removes the env from tracking entirely
        info = await self.provisioner.get_info(env_id)
        self.assertIsNone(info)

    async def test_list_all(self):
        """list_all reflects created environments."""
        config = _make_config()
        ids = [_unique_id(f"list-{i}") for i in range(2)]
        for eid in ids:
            await self.provisioner.create(eid, config=config)

        all_envs = await self.provisioner.list_all()
        listed_ids = {e.env_id for e in all_envs}
        for eid in ids:
            self.assertIn(eid, listed_ids)


# ---------------------------------------------------------------------------
# EnvPoolManager tests
# ---------------------------------------------------------------------------

class TestEnvPoolManager(_DockerTestBase):

    manager: EnvPoolManager

    def setUp(self):
        super().setUp()
        self.manager = EnvPoolManager(
            provisioner=self.provisioner,
            max_pool_size=10,
            auto_scale=True,
            acquisition_timeout=180.0,
        )

    async def asyncTearDown(self):
        try:
            if FAST_CLEANUP:
                pass  # containers preserved
            else:
                await self.manager.cleanup()
        except Exception:
            pass

    async def test_provision_single(self):
        """Provision one environment into the pool."""
        config = _make_config()
        envs = await self.manager.provision(num_envs=1, config=config)

        self.assertEqual(len(envs), 1)
        self.assertEqual(envs[0].status, EnvStatus.READY)

        stats = self.manager.get_stats()
        self.assertEqual(stats.total_envs, 1)
        self.assertEqual(stats.ready_envs, 1)

    async def test_provision_parallel(self):
        """Provision multiple environments in parallel."""
        config = _make_config()
        envs = await self.manager.provision(num_envs=3, config=config, parallel=True)

        self.assertEqual(len(envs), 3)
        stats = self.manager.get_stats()
        self.assertEqual(stats.total_envs, 3)
        self.assertEqual(stats.ready_envs, 3)

    async def test_acquire_release(self):
        """Acquire assigns an env; release returns it to the pool."""
        config = _make_config()
        await self.manager.provision(num_envs=1, config=config)

        env = await self.manager.acquire(agent_id="agent-1", config=config)
        self.assertEqual(env.status, EnvStatus.IN_USE)
        self.assertEqual(env.assigned_agent, "agent-1")

        stats = self.manager.get_stats()
        self.assertEqual(stats.in_use_envs, 1)
        self.assertEqual(stats.ready_envs, 0)

        await self.manager.release(env.env_id)

        stats = self.manager.get_stats()
        self.assertEqual(stats.in_use_envs, 0)
        self.assertEqual(stats.ready_envs, 1)

    async def test_auto_scale(self):
        """Acquire without pre-provisioning triggers auto-scale."""
        config = _make_config()
        self.assertEqual(self.manager.get_ready_count(), 0)

        env = await self.manager.acquire(agent_id="agent-auto", config=config)

        self.assertIsNotNone(env)
        self.assertEqual(env.assigned_agent, "agent-auto")
        stats = self.manager.get_stats()
        self.assertEqual(stats.total_envs, 1)
        self.assertEqual(stats.in_use_envs, 1)

    async def test_multiple_agents(self):
        """Multiple agents each get a distinct environment."""
        config = _make_config()
        await self.manager.provision(num_envs=3, config=config)

        agents = ["agent-1", "agent-2", "agent-3"]
        envs = [
            await self.manager.acquire(agent_id=aid, config=config)
            for aid in agents
        ]

        env_ids = {e.env_id for e in envs}
        self.assertEqual(len(env_ids), 3, "each agent should get a different env")

        stats = self.manager.get_stats()
        self.assertEqual(stats.in_use_envs, 3)
        self.assertEqual(stats.ready_envs, 0)

        for env in envs:
            await self.manager.release(env.env_id)

        stats = self.manager.get_stats()
        self.assertEqual(stats.in_use_envs, 0)
        self.assertEqual(stats.ready_envs, 3)

    async def test_stats_tracking(self):
        """Stats correctly reflect acquisitions and releases."""
        config = _make_config()
        await self.manager.provision(num_envs=2, config=config)

        env1 = await self.manager.acquire(agent_id="a1", config=config)
        env2 = await self.manager.acquire(agent_id="a2", config=config)
        await self.manager.release(env1.env_id)

        stats = self.manager.get_stats()
        self.assertEqual(stats.total_acquisitions, 2)
        self.assertEqual(stats.total_releases, 1)
        self.assertEqual(stats.in_use_envs, 1)
        self.assertEqual(stats.ready_envs, 1)

    async def test_container_reuse(self):
        """Provisioning with reuse_existing recovers stopped containers."""
        config = _make_config()

        # Create and stop a container (simulates a previous run).
        envs = await self.manager.provision(num_envs=1, config=config)
        original_id = envs[0].env_id
        container_name = f"mcp-env-{original_id}"
        await self.provisioner._run_docker_cmd(["stop", container_name], check=False)

        # Create a fresh manager (simulates a new process).
        manager2 = EnvPoolManager(
            provisioner=DockerProvisioner(
                docker_host=DOCKER_HOST,
                host=GATEWAY_HOST,
                base_port=9000,
                startup_timeout=180.0,
                build_context=str(_PROJECT_ROOT),
                auto_build=True,
                image_prefix="mcp-universe/test-gateway",
            ),
            max_pool_size=10,
            auto_scale=True,
            acquisition_timeout=180.0,
        )

        reused = await manager2.provision(num_envs=1, config=config, reuse_existing=True)
        self.assertEqual(len(reused), 1)

        # Cleanup the second manager too.
        await manager2.cleanup()


# ---------------------------------------------------------------------------
# Multi-pod (multiple provisioners) tests
# ---------------------------------------------------------------------------

def _make_provisioner(docker_host: str, host: str) -> DockerProvisioner:
    """Create a DockerProvisioner for the given Docker host."""
    return DockerProvisioner(
        docker_host=docker_host,
        host=host,
        base_port=9000,
        startup_timeout=180.0,
        build_context=str(_PROJECT_ROOT),
        auto_build=True,
        image_prefix="mcp-universe/test-gateway",
    )


@unittest.skipUnless(DOCKER_HOST, "CPU_POD_DOCKER_HOST not set")
@unittest.skipUnless(DOCKER_HOST_2, "CPU_POD_DOCKER_HOST_2 not set")
@unittest.skipUnless(_DOCKERFILE.exists(), f"{_DOCKERFILE} not found")
class TestMultiPodScheduling(unittest.IsolatedAsyncioTestCase):
    """Tests for multi-provisioner (multi-pod) scheduling."""

    def setUp(self):
        self.prov1 = _make_provisioner(DOCKER_HOST, GATEWAY_HOST)
        self.prov2 = _make_provisioner(DOCKER_HOST_2, GATEWAY_HOST_2)

    async def asyncTearDown(self):
        for p in (self.prov1, self.prov2):
            try:
                if FAST_CLEANUP:
                    await p.reset_all()
                else:
                    await p.cleanup_all()
            except Exception:
                pass

    async def test_least_loaded_distributes_evenly(self):
        """Least-loaded scheduling spreads environments across pods."""
        manager = EnvPoolManager(
            provisioner=self.prov1,
            provisioners=[self.prov1, self.prov2],
            scheduling="least-loaded",
            max_pool_size=10,
            acquisition_timeout=180.0,
        )
        config = _make_config()

        # Provision 4 environments one-by-one (sequential to observe ordering).
        # reuse_existing=False ensures we exercise the scheduling path
        # instead of recovering leftover containers from a single host.
        await manager.provision(num_envs=4, config=config, parallel=False,
                                reuse_existing=False)

        stats = manager.get_provisioner_stats()
        counts = [s["env_count"] for s in stats]
        # Each provisioner should get 2.
        self.assertEqual(counts, [2, 2],
                         f"Expected even 2-2 split, got {counts}")

        await manager.cleanup()

    async def test_least_loaded_fills_lighter_node_first(self):
        """When one pod already has load, new envs go to the lighter pod."""
        manager = EnvPoolManager(
            provisioner=self.prov1,
            provisioners=[self.prov1, self.prov2],
            scheduling="least-loaded",
            max_pool_size=10,
            acquisition_timeout=180.0,
        )
        config = _make_config()

        # Provision 1 env — goes to prov1 (both empty, lower index wins).
        await manager.provision(num_envs=1, config=config, parallel=False,
                                reuse_existing=False)
        stats = manager.get_provisioner_stats()
        self.assertEqual(stats[0]["env_count"], 1)
        self.assertEqual(stats[1]["env_count"], 0)

        # Provision 2 more — first should go to prov2, second evens out.
        await manager.provision(num_envs=2, config=config, parallel=False,
                                reuse_existing=False)
        stats = manager.get_provisioner_stats()
        counts = [s["env_count"] for s in stats]
        # 3 envs total: expected 2-1 (prov1 started with 1, next goes to
        # prov2, then they tie at 1-1 so prov1 gets the third).
        self.assertEqual(sum(counts), 3)
        self.assertLessEqual(abs(counts[0] - counts[1]), 1,
                             f"Load should differ by at most 1, got {counts}")

        await manager.cleanup()

    async def test_round_robin_cycles_in_order(self):
        """Round-robin ignores load and cycles through provisioners."""
        manager = EnvPoolManager(
            provisioner=self.prov1,
            provisioners=[self.prov1, self.prov2],
            scheduling="round-robin",
            max_pool_size=10,
            acquisition_timeout=180.0,
        )
        config = _make_config()

        await manager.provision(num_envs=4, config=config, parallel=False,
                                reuse_existing=False)

        stats = manager.get_provisioner_stats()
        counts = [s["env_count"] for s in stats]
        # Round-robin with 4 envs on 2 provisioners: 2-2.
        self.assertEqual(counts, [2, 2],
                         f"Round-robin 4 envs on 2 pods should be 2-2, got {counts}")

        await manager.cleanup()

    async def test_provisioner_stats_reflects_acquire_release(self):
        """get_provisioner_stats updates after acquire and release cycles."""
        manager = EnvPoolManager(
            provisioner=self.prov1,
            provisioners=[self.prov1, self.prov2],
            scheduling="least-loaded",
            max_pool_size=10,
            auto_scale=True,
            acquisition_timeout=180.0,
        )
        config = _make_config()

        await manager.provision(num_envs=2, config=config, parallel=False,
                                reuse_existing=False)
        stats_before = manager.get_provisioner_stats()
        self.assertEqual(stats_before[0]["env_count"], 1)
        self.assertEqual(stats_before[1]["env_count"], 1)

        # Acquire one, destroy it — the provisioner that owned it loses count.
        env = await manager.acquire(agent_id="agent-x", config=config)
        await manager.destroy(env.env_id)

        stats_after = manager.get_provisioner_stats()
        total = sum(s["env_count"] for s in stats_after)
        self.assertEqual(total, 1, "One env destroyed, one should remain")

        await manager.cleanup()

    async def test_multi_pod_acquire_release(self):
        """Agents can acquire and release envs spread across pods."""
        manager = EnvPoolManager(
            provisioner=self.prov1,
            provisioners=[self.prov1, self.prov2],
            scheduling="least-loaded",
            max_pool_size=10,
            acquisition_timeout=180.0,
        )
        config = _make_config()

        await manager.provision(num_envs=4, config=config, parallel=False,
                                reuse_existing=False)

        # Acquire all 4.
        envs = [
            await manager.acquire(agent_id=f"agent-{i}", config=config)
            for i in range(4)
        ]
        self.assertEqual(len(envs), 4)
        self.assertEqual(manager.get_in_use_count(), 4)
        self.assertEqual(manager.get_ready_count(), 0)

        # Each env should have a reachable gateway address.
        hosts_seen = set()
        for env in envs:
            self.assertTrue(env.gateway_address.startswith("http://"))
            hosts_seen.add(env.gateway_address.split("//")[1].split(":")[0])

        # We should see addresses from both pods.
        self.assertEqual(len(hosts_seen), 2,
                         f"Expected 2 distinct hosts, got {hosts_seen}")

        # Release all.
        for env in envs:
            await manager.release(env.env_id)

        self.assertEqual(manager.get_in_use_count(), 0)
        self.assertEqual(manager.get_ready_count(), 4)

        await manager.cleanup()
