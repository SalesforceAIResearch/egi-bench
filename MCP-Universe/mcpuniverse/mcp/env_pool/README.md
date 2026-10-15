# Environment Pool (`env_pool`)

Manages a pool of isolated MCP environments backed by Docker containers.
Each environment runs an MCP Gateway plus one or more MCP servers, and can
be acquired by an agent, used, then released back to the pool for reuse.

## Core Concepts

| Concept | Description |
|---|---|
| **EnvConfig** | Declares what an environment looks like: which MCP servers to run, resource limits, Dockerfile, etc. |
| **EnvInfo** | Runtime metadata for a live environment: ID, status, gateway address, assigned agent. |
| **BaseProvisioner** | Abstract interface for creating / destroying / resetting environments. |
| **DockerProvisioner** | Concrete provisioner that manages Docker containers (local or remote). |
| **EnvPoolManager** | Orchestrates a pool of environments: provisioning, acquire/release, health checks, auto-scaling. |

## Quick Start

```python
from mcpuniverse.mcp.env_pool import (
    EnvPoolManager, DockerProvisioner, EnvConfig,
)

# 1. Configure what each environment should run
config = EnvConfig(servers=["playwright", "weather"])

# 2. Create a provisioner (one per Docker host)
provisioner = DockerProvisioner(
    config=config,
    host="localhost",
)

# 3. Create the pool manager
pool = EnvPoolManager(
    provisioner,
    max_pool_size=20,
    auto_scale=True,
    min_ready_envs=5,
)

# 4. Pre-provision some environments
await pool.provision(num_envs=10)

# 5. An agent acquires an environment
env = await pool.acquire(agent_id="agent-1")
print(env.gateway_address)  # e.g. http://localhost:9001

# 6. Agent is done — release back to the pool
await pool.release(env.env_id)

# 7. Tear everything down
await pool.cleanup()
```

## Multi-Host / Load Balancing

Pass multiple provisioners to spread environments across hosts:

```python
p1 = DockerProvisioner(docker_host="tcp://host-a:2375", host="host-a")
p2 = DockerProvisioner(docker_host="tcp://host-b:2375", host="host-b")

pool = EnvPoolManager(
    provisioner=p1,
    provisioners=[p1, p2],
    scheduling="least-loaded",   # default — picks the node with fewest envs
    # scheduling="round-robin",  # simple cyclic selection
)
```

Inspect per-provisioner load at any time:

```python
pool.get_provisioner_stats()
# [{"index": 0, "provisioner": "...", "env_count": 5},
#  {"index": 1, "provisioner": "...", "env_count": 3}]
```

## Key Parameters

### `EnvConfig`

| Parameter | Default | Description |
|---|---|---|
| `servers` | `[]` | MCP servers to run inside the environment |
| `dockerfile_path` | `None` | Custom Dockerfile (auto-built if provided) |
| `gateway_port` | `8000` | Gateway port inside the container |
| `gateway_mode` | `"sse"` | `"sse"` or `"stdio"` |
| `cpu_limit` | `"2"` | CPU cores |
| `memory_limit` | `"4g"` | Memory limit |
| `env_vars` | `{}` | Extra environment variables |

### `EnvPoolManager`

| Parameter | Default | Description |
|---|---|---|
| `max_pool_size` | `50` | Maximum environments in the pool |
| `min_ready_envs` | `0` | Maintain at least this many ready environments |
| `auto_scale` | `False` | Provision on-demand when no ready env is available |
| `health_check_interval` | `30.0` | Seconds between health-check rounds |
| `reset_on_release` | `False` | Restart the container when released |
| `acquisition_timeout` | `60.0` | Default `acquire()` timeout (seconds) |
| `scheduling` | `"least-loaded"` | Provisioner selection: `"least-loaded"` or `"round-robin"` |

## Background Tasks

```python
pool.start_background_tasks()
```

Starts two optional loops:

- **Health check** — periodically verifies containers are alive; resets or
  marks them as errored if not.
- **Auto-scale** — provisions new environments when `ready_envs` drops below
  `min_ready_envs`.

## Pool Statistics

```python
stats = pool.get_stats()
stats.total_envs          # total managed environments
stats.ready_envs          # available for acquisition
stats.in_use_envs         # currently assigned to agents
stats.total_acquisitions  # lifetime acquire count
stats.avg_acquisition_wait_ms  # average acquire() wait time (ms)
stats.avg_usage_duration_s     # average env hold time per agent (s)
```
