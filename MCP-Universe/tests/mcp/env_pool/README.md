# env_pool Integration Tests

Integration tests against real Docker daemons, covering the full lifecycle of
`DockerProvisioner` and `EnvPoolManager`.

## Prerequisites

- At least one accessible Docker daemon with TCP API exposed (e.g. `tcp://<host>:2375`)
- `Dockerfile.test` in this directory (already included in the repo)

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `CPU_POD_DOCKER_HOST` | Yes | Docker API endpoint, e.g. `tcp://<host>:2375` |
| `CPU_POD_HOST` | No | IP/hostname where containers are reachable (default: `localhost`) |
| `CPU_POD_DOCKER_HOST_2` | Multi-pod tests only | Docker API endpoint for the second host |
| `CPU_POD_HOST_2` | Multi-pod tests only | Reachable IP for the second pod |
| `FAST_CLEANUP` | No | Set to `true` to reset (not destroy) containers between tests for faster iteration |

**All tests are automatically skipped when environment variables are not set.** No extra configuration needed for CI / GitHub Actions.

## Running Tests

### Single Pod (DockerProvisioner + EnvPoolManager basics)

```bash
export CPU_POD_DOCKER_HOST="tcp://<docker-host>:2375"
export CPU_POD_HOST="<reachable-ip>"

python -m pytest tests/mcp/env_pool/test_env_pool.py -v -s
```

### Multi-Pod (scheduling strategy tests)

Requires two different Docker hosts to verify `least-loaded` and `round-robin` scheduling:

```bash
export CPU_POD_DOCKER_HOST="tcp://<docker-host-1>:2375"
export CPU_POD_HOST="<reachable-ip-1>"
export CPU_POD_DOCKER_HOST_2="tcp://<docker-host-2>:2375"
export CPU_POD_HOST_2="<reachable-ip-2>"

python -m pytest tests/mcp/env_pool/test_env_pool.py -v -s
```

### Running a specific test class

```bash
# DockerProvisioner low-level tests only
python -m pytest tests/mcp/env_pool/test_env_pool.py::TestDockerProvisioner -v -s

# EnvPoolManager pool management tests only
python -m pytest tests/mcp/env_pool/test_env_pool.py::TestEnvPoolManager -v -s

# Multi-pod scheduling tests only
python -m pytest tests/mcp/env_pool/test_env_pool.py::TestMultiPodScheduling -v -s
```

## Test Inventory

### TestDockerProvisioner — single-container lifecycle

| Test | Validates |
|---|---|
| `test_docker_connection` | Basic connectivity to the Docker daemon |
| `test_create_single_env` | Container creation and READY status |
| `test_create_multiple_envs` | Multiple containers get distinct ports |
| `test_health_check` | Health check returns True for a running container |
| `test_reset_env` | Reset restarts the container back to READY |
| `test_destroy_env` | Destroy removes the container from tracking |
| `test_list_all` | list_all reflects all created environments |

### TestEnvPoolManager — pool management

| Test | Validates |
|---|---|
| `test_provision_single` | Provision one environment into the pool |
| `test_provision_parallel` | Parallel provisioning of multiple environments |
| `test_acquire_release` | Acquire assigns an env; release returns it |
| `test_auto_scale` | Auto-provisions when pool is empty |
| `test_multiple_agents` | Each agent gets a distinct environment |
| `test_stats_tracking` | Stats update correctly on acquire/release |
| `test_container_reuse` | Recovers stopped containers instead of creating new ones |

### TestMultiPodScheduling — multi-pod scheduling

| Test | Validates |
|---|---|
| `test_least_loaded_distributes_evenly` | Least-loaded distributes environments evenly across pods |
| `test_least_loaded_fills_lighter_node_first` | New environments go to the lighter node first |
| `test_round_robin_cycles_in_order` | Round-robin cycles through provisioners in order |
| `test_provisioner_stats_reflects_acquire_release` | Stats decrease correctly after destroy |
| `test_multi_pod_acquire_release` | Full acquire/release cycle across two pods |

## Cleaning Up Leftover Containers

If tests are interrupted and leave containers behind, clean up manually:

```bash
docker -H tcp://<docker-host>:2375 ps -a --filter "name=mcp-env-" -q \
  | xargs -r docker -H tcp://<docker-host>:2375 rm -f
```
