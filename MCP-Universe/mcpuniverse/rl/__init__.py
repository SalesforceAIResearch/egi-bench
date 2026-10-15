"""
MCP-Universe RL - Rollout engine for RL training.

Uses MCP-Universe's native Agent and LLM components.

Quick Start:
```python
from mcpuniverse.rl import RolloutEngine, rollout

engine = RolloutEngine.from_config("config.yaml")
output = await engine.run([{"instruction": "What's the weather?"}])
```
"""

from .config import (
    RolloutConfig,
    TrajectoryConfig,
    GeneratorConfig,
    DispatcherConfig,
    ServerConfig,
    AgentMode,
    EnvPoolConfig,
    DockerBuildConfig,
    ContainerResourceConfig,
)

from .trajectory import (
    Trajectory,
    TrajectoryResult,
    TrajectoryStep,
    TraceData,
    TokenData,
    create_trajectory,
    create_llm
)

from .dispatcher import (
    get_dispatcher,
    DISPATCHER_REGISTRY
)

from .runner import (
    RolloutEngine,
    RolloutOutput,
    rollout
)

from .formatters import (
    BaseFormatter,
    FormatterOutput,
    GptOssFormatter,
    get_formatter,
    FORMATTERS
)


__all__ = [
    # Config
    "RolloutConfig",
    "TrajectoryConfig",
    "GeneratorConfig",
    "DispatcherConfig",
    "ServerConfig",
    "AgentMode",
    "EnvPoolConfig",
    "DockerBuildConfig",
    "ContainerResourceConfig",

    # Trajectory
    "Trajectory",
    "TrajectoryResult",
    "TrajectoryStep",
    "TraceData",
    "TokenData",
    "create_trajectory",
    "create_llm",

    # Dispatcher
    "get_dispatcher",
    "DISPATCHER_REGISTRY",

    # Runner
    "RolloutEngine",
    "RolloutOutput",
    "rollout",

    # Formatters (model-specific prompt/output splitting)
    "BaseFormatter",
    "FormatterOutput",
    "GptOssFormatter",
    "get_formatter",
    "FORMATTERS",
]
