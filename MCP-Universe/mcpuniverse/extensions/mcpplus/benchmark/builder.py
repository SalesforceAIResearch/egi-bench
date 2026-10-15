"""
Extended Workflow Builder with Wrapper Support

EXISTING (MCPUniverse WorkflowBuilder):
- Parses YAML configs with 3 kinds: llm, agent, workflow
- Builds dependency graph and instantiates components
- Uses standard MCPManager for MCP protocol

THIS IMPLEMENTATION:
- Extends to support 4th kind: wrapper (for PostProcessAgent config)
- Pre-parses wrapper configs and builds MCPWrapperManager when enabled
- Filters wrapper configs before passing to parent
"""
from typing import List, Literal, Dict, Any, Optional

from pydantic import BaseModel
from mcpuniverse.workflows.builder import WorkflowBuilder as BaseWorkflowBuilder
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.agent.base import Executor
from mcpuniverse.common.context import Context
from mcpuniverse.common.logger import get_logger

from mcpuniverse.extensions.mcpplus.wrapper.wrapper_manager import MCPWrapperManager, WrapperConfig


class WrapperSpec(BaseModel):
    """
    Wrapper specification for post-processing.

    Attributes:
        enabled (bool): Enable/disable wrapper functionality.
        token_threshold (int): Minimum token count to trigger post-processing.
        post_process_llm (Dict, optional): LLM config for post-processor. Defaults to gpt-5-mini.
        llm_timeout (int): Max seconds for LLM API calls during post-processing.
        max_iterations (int): Maximum iterations for post-processor refinement.
        skip_iteration_on_size_failure (bool): Return original if both outputs too large.
    """
    enabled: bool = False
    token_threshold: int = 2000
    post_process_llm: Optional[Dict] = None
    llm_timeout: int = 500
    max_iterations: int = 3
    skip_iteration_on_size_failure: bool = False


class ExtendedWorkflowConfig(BaseModel):
    """
    Extended workflow configuration that supports wrapper configs.

    Attributes:
        kind (Literal): The kind of component being configured.
        spec (WrapperSpec | dict): The specification for the component.
    """
    kind: Literal["llm", "agent", "workflow", "wrapper"]
    spec: WrapperSpec | dict


class WorkflowBuilderWithWrapper(BaseWorkflowBuilder):
    """
    Extended WorkflowBuilder that supports wrapper configurations.

    This class extends MCPUniverse's WorkflowBuilder to:
    1. Parse "wrapper" kind configurations from YAML
    2. Build MCPWrapperManager when wrapper is configured
    3. Inject wrapper configs into agents that reference them
    """

    def __init__(
        self,
        mcp_manager: Optional[MCPManager] = None,
        config: str | dict | List[dict] = None,
        context: Optional[Context] = None
    ):
        """
        Initialize the extended workflow builder.

        Args:
            mcp_manager (MCPManager, optional): An MCP manager. If None and wrapper is configured,
                                                MCPWrapperManager will be created.
            config (str | dict | List[dict]): Configuration source.
            context (Context, optional): Context information.
        """
        self._context = context if context else Context()
        self._wrapper_config: Optional[WrapperConfig] = None
        self._wrapper_llm_ref: Optional[str] = None
        self._logger = get_logger(self.__class__.__name__)

        # Parse wrapper config before initializing base class
        self._parse_wrapper_config(config)

        # Determine which MCP manager to use
        if mcp_manager is None:
            if self._wrapper_config:
                # Use MCPWrapperManager if wrapper is configured
                mcp_manager = MCPWrapperManager(
                    wrapper_config=self._wrapper_config,
                    context=self._context
                )
            else:
                # Use standard MCPManager
                mcp_manager = MCPManager(context=self._context)

        self._mcp_manager = mcp_manager

        # Filter out wrapper configs before passing to base class
        filtered_config = self._filter_wrapper_configs(config)

        # Initialize base class
        super().__init__(mcp_manager=mcp_manager, config=filtered_config)

    def _parse_wrapper_config(self, config: str | dict | List[dict]):
        """
        Parse wrapper configuration from the config.

        Args:
            config (str | dict | List[dict]): Configuration source.
        """
        if not config:
            return

        # Load as extended configs
        import yaml
        if isinstance(config, str):
            with open(config, "r", encoding="utf-8") as f:
                objects = yaml.safe_load_all(f)
                if isinstance(objects, dict):
                    objects = [objects]
                configs = [ExtendedWorkflowConfig.model_validate(o) for o in objects]
        elif isinstance(config, dict):
            configs = [ExtendedWorkflowConfig.model_validate(config)]
        else:
            configs = [ExtendedWorkflowConfig.model_validate(o) for o in config]

        # Extract wrapper config (only one wrapper config supported)
        for conf in configs:
            if conf.kind == "wrapper":
                wrapper_spec = WrapperSpec.model_validate(conf.spec)
                self._wrapper_config = WrapperConfig(
                    enabled=wrapper_spec.enabled,
                    token_threshold=wrapper_spec.token_threshold,
                    post_process_llm=wrapper_spec.post_process_llm,
                    llm_timeout=wrapper_spec.llm_timeout,
                    max_iterations=wrapper_spec.max_iterations,
                    skip_iteration_on_size_failure=wrapper_spec.skip_iteration_on_size_failure
                )
                # Track LLM reference if post_process_llm is specified and is a dict with 'llm' key
                if isinstance(wrapper_spec.post_process_llm, dict) and 'llm' in wrapper_spec.post_process_llm:
                    self._wrapper_llm_ref = wrapper_spec.post_process_llm['llm']
                break  # Only support one wrapper config

    def _filter_wrapper_configs(self, config: str | dict | List[dict]) -> str | dict | List[dict]:
        """
        Filter out wrapper configurations from config before passing to base class.
        Also removes 'wrapper' field from agent configs.

        Args:
            config (str | dict | List[dict]): Original configuration.

        Returns:
            Filtered configuration without wrapper kinds and without wrapper references in agents.
        """
        if isinstance(config, str):
            # For file paths, we need to load, filter, and pass as list
            import yaml
            with open(config, "r", encoding="utf-8") as f:
                objects = list(yaml.safe_load_all(f))
            filtered = [obj for obj in objects if obj.get("kind") != "wrapper"]
            # Also remove wrapper references from agent configs
            for obj in filtered:
                if obj.get("kind") in ["agent", "workflow"]:
                    if "wrapper" in obj.get("spec", {}).get("config", {}):
                        del obj["spec"]["config"]["wrapper"]
            return filtered
        elif isinstance(config, dict):
            if config.get("kind") == "wrapper":
                return []
            return config
        else:  # list
            filtered = [obj for obj in config if obj.get("kind") != "wrapper"]
            # Remove wrapper references
            for obj in filtered:
                if obj.get("kind") in ["agent", "workflow"]:
                    if "wrapper" in obj.get("spec", {}).get("config", {}):
                        del obj["spec"]["config"]["wrapper"]
            return filtered

    def build(
            self,
            components: Optional[Dict[str, BaseLLM | Executor]] = None,
            project_id: Optional[str] = "local_test"
    ):
        """
        Build the agent workflow with wrapper LLM resolution.

        This method extends the parent build() to:
        1. Build all components normally
        2. Resolve LLM references in wrapper config
        3. Set the LLM on MCPWrapperManager if needed

        Args:
            components (Dict, optional): Pre-built components to use.
            project_id (str, optional): The project ID for this workflow.
        """
        # Call parent build
        super().build(components=components, project_id=project_id)

        # Resolve wrapper LLM reference if MCPWrapperManager is used
        if isinstance(self._mcp_manager, MCPWrapperManager) and self._wrapper_llm_ref:
            if self._wrapper_llm_ref in self._name2object:
                llm = self._name2object[self._wrapper_llm_ref]
                self._mcp_manager.set_llm(llm)
                self._logger.debug(
                    "Set post-processor LLM '%s' for wrapper",
                    self._wrapper_llm_ref
                )
