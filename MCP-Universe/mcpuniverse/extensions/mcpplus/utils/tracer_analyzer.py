"""
Tracer analyzer for extracting metrics from execution traces.

This module analyzes tracer logs to compute:
- Iteration counts for main agent and post-processor
- Token usage from LLM calls
- Cost calculations based on model pricing
"""
# pylint: disable=too-many-instance-attributes,too-few-public-methods
# pylint: disable=unused-argument,too-many-return-statements
import json
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from mcpuniverse.tracer.collectors.base import BaseCollector
from mcpuniverse.common.logger import get_logger
from mcpuniverse.extensions.mcpplus.utils.stats import count_tokens  # pylint: disable=no-name-in-module


@dataclass
class AgentMetrics:
    """Metrics for a single agent's execution."""
    agent_name: str  # From config (e.g., "ReAct-agent")
    llm_name: str    # From config (e.g., "main-llm", "postprocessor-llm")
    model_name: str  # Actual model (e.g., "gpt-4o")
    iterations: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_cost: float   # Separate input cost
    output_cost: float  # Separate output cost
    total_cost: float   # Sum of input + output
    llm_calls: int


@dataclass
class TaskMetrics:
    """Complete metrics for a task execution."""
    trace_id: str
    main_agent: AgentMetrics
    postprocessor: Optional[AgentMetrics]

    # Totals
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_input_cost: float
    total_output_cost: float
    total_cost: float

    # Post-processor specific (from wrapper stats if available)
    postprocessor_iterations: int = 0
    original_chars: int = 0
    filtered_chars: int = 0
    chars_reduced: int = 0
    original_tokens: int = 0
    filtered_tokens: int = 0
    tokens_reduced: int = 0


class TracerAnalyzer:
    """Analyze tracer logs to extract execution metrics."""

    # Model pricing (input/output per 1M tokens)
    MODEL_PRICING = {
        "gpt-4o": {"input": 2.5, "output": 10.0},
        "gpt-4.1": {"input": 2.0, "output": 8.0},  
        "gpt-5": {"input": 1.25, "output": 10.0},  
        "gpt-5-mini": {"input": 0.25, "output": 2.0},   
        "gpt-5-mini-2025-08-07": {"input": 0.25, "output": 2.0},   
        "claude-sonnet-4": {"input": 3.0, "output": 15.0},
        "claude-sonnet-3.7": {"input": 3.0, "output": 15.0},
        "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
        "gemini-3-pro-preview": {"input": 2.0, "output": 12.0},
        "gemini-3-flash-preview": {"input": 0.5, "output": 3.0},
        "GLM4_6_OR": {"input": 0.55, "output": 2.19},
        # Add more as needed
    }

    def __init__(
        self,
        trace_collector: BaseCollector,
        agent_configs: List[Dict[str, Any]]
    ):
        """
        Initialize tracer analyzer.

        Args:
            trace_collector: Collector to read traces from.
            agent_configs: List of agent/LLM configs from YAML.
        """
        self.collector = trace_collector
        self.agent_configs = agent_configs
        self._logger = get_logger(self.__class__.__name__)

        # Build lookup maps from configs
        self._build_config_maps()

    def _build_config_maps(self):
        """
        Build lookup maps for agent names, LLM names, and LLM classes.

        Creates:
        - agent_name_map: {agent_type -> agent_name}
        - llm_name_map: {llm_class -> llm_name}
        - agent_llm_map: {agent_name -> llm_name}
        - llm_model_map: {llm_name -> model_name}
        """
        self.agent_name_map = {}  # "react" -> "ReAct-agent"
        self.llm_name_map = {}    # "OpenAIModel" -> "main-llm"
        self.agent_llm_map = {}   # "ReAct-agent" -> "main-llm"
        self.llm_model_map = {}   # "main-llm" -> "us.anthropic.claude-sonnet-4..."
        self.postprocessor_llm_name = None  # Track postprocessor LLM name

        for config in self.agent_configs:
            kind = config.get('kind')
            spec = config.get('spec', {})

            if kind == 'agent':
                agent_name = spec.get('name')
                agent_type = spec.get('type')  # "react", etc.
                agent_config = spec.get('config', {})
                llm_ref = agent_config.get('llm')  # LLM reference

                # Map agent type to name
                if agent_type and agent_name:
                    # Store mapping: type -> name (for matching trace records)
                    self.agent_name_map[agent_type.lower()] = agent_name

                # Map agent to its LLM
                if agent_name and llm_ref:
                    self.agent_llm_map[agent_name] = llm_ref

            elif kind == 'llm':
                llm_name = spec.get('name')
                llm_type = spec.get('type')  # "openai", "claude_gateway", etc.
                llm_config = spec.get('config', {})
                model_name = llm_config.get('model_name')

                # Map LLM name to model
                if llm_name and model_name:
                    self.llm_model_map[llm_name] = model_name

                # Map LLM class to name (for matching trace records)
                if llm_name:
                    # Build expected class name from type
                    if llm_type == 'openai':
                        self.llm_name_map['OpenAIModel'] = llm_name
                    # Add more mappings as needed

            elif kind == 'wrapper':
                wrapper_spec = spec
                post_llm_config = wrapper_spec.get('post_process_llm', {})
                if post_llm_config:
                    self.postprocessor_llm_name = post_llm_config.get('llm')

        self._logger.debug("Config maps built: agents=%s, llms=%s",
                         self.agent_name_map, self.llm_name_map)

    def analyze_task(self, trace_id: str, postprocessor_trace_id: Optional[str] = None) -> TaskMetrics:
        """
        Analyze a complete task execution.

        Args:
            trace_id: Main agent trace ID to analyze.
            postprocessor_trace_id: Optional separate post-processor trace ID.
                If provided, will load and analyze post-processor records separately.

        Returns:
            TaskMetrics with all computed metrics.
        """
        # Load all trace records from main agent
        records = self._load_trace_records(trace_id)

        if not records:
            self._logger.warning("No records found for trace_id=%s", trace_id)
            # Return empty metrics
            default_agent = AgentMetrics(
                agent_name="unknown",
                llm_name="unknown",
                model_name="gpt-4",
                iterations=0,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                input_cost=0.0,
                output_cost=0.0,
                total_cost=0.0,
                llm_calls=0
            )
            return TaskMetrics(
                trace_id=trace_id,
                main_agent=default_agent,
                postprocessor=None,
                total_input_tokens=0,
                total_output_tokens=0,
                total_tokens=0,
                total_input_cost=0.0,
                total_output_cost=0.0,
                total_cost=0.0
            )

        # Separate records by agent type
        main_agent_records, postprocessor_records = self._separate_agent_records(records)

        # If postprocessor_trace_id is provided, load those records separately
        if postprocessor_trace_id:
            self._logger.debug("Loading separate post-processor trace: %s", postprocessor_trace_id)
            postprocessor_records = self._load_trace_records(postprocessor_trace_id)
            self._logger.debug("Loaded %d post-processor records", len(postprocessor_records))

            # Debug: Check what types of records we have
            if postprocessor_records:
                record_types = [rec.data.get('type', 'unknown') if hasattr(rec, 'data') else 'no-data'
                               for rec in postprocessor_records[:5]]
                self._logger.debug("Sample record types: %s", record_types)
        else:
            self._logger.warning("No postprocessor_trace_id provided, looking in main trace")

        # Get agent name from first record or config
        main_agent_name = self._extract_agent_name(main_agent_records, is_main=True)

        # Analyze main agent
        main_metrics = self._analyze_agent_records(
            main_agent_records,
            agent_name=main_agent_name,
            is_postprocessor=False
        )

        # Analyze post-processor (if any)
        postprocessor_metrics = None

        if postprocessor_records:
            pp_agent_name = "PostProcessAgent"  # Fixed name for postprocessor
            postprocessor_metrics = self._analyze_agent_records(
                postprocessor_records,
                agent_name=pp_agent_name,
                is_postprocessor=True
            )

        # Calculate totals
        total_input = main_metrics.input_tokens
        total_output = main_metrics.output_tokens
        total_input_cost = main_metrics.input_cost
        total_output_cost = main_metrics.output_cost
        total_cost = main_metrics.total_cost

        if postprocessor_metrics:
            total_input += postprocessor_metrics.input_tokens
            total_output += postprocessor_metrics.output_tokens
            total_input_cost += postprocessor_metrics.input_cost
            total_output_cost += postprocessor_metrics.output_cost
            total_cost += postprocessor_metrics.total_cost

        return TaskMetrics(
            trace_id=trace_id,
            main_agent=main_metrics,
            postprocessor=postprocessor_metrics,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_tokens=total_input + total_output,
            total_input_cost=total_input_cost,
            total_output_cost=total_output_cost,
            total_cost=total_cost,
            postprocessor_iterations=postprocessor_metrics.iterations if postprocessor_metrics else 0
        )

    def _load_trace_records(self, trace_id: str) -> List[Dict[str, Any]]:
        """
        Load all records for a trace from the collector.

        Args:
            trace_id: Trace ID to load.

        Returns:
            List of record dictionaries.
        """
        # Get trace records from collector's in-memory store
        trace_records = self.collector.get(trace_id)

        # Convert TraceRecord objects to dict format
        records = []
        for trace_record in trace_records:
            # TraceRecord has a 'records' field containing the actual execution records
            if hasattr(trace_record, 'records'):
                records.extend(trace_record.records)

        self._logger.debug("Loaded %d records for trace_id=%s", len(records), trace_id)
        return records

    def _separate_agent_records(
        self,
        records: List[Any]
    ) -> Tuple[List[Any], List[Any]]:
        """
        Separate records into main agent and post-processor records.

        Args:
            records: All records from trace (DataRecord objects).

        Returns:
            Tuple of (main_agent_records, postprocessor_records)
        """
        main_records = []
        postprocessor_records = []

        for record in records:
            # DataRecord has 'data' attribute (dict)
            data = record.data if hasattr(record, 'data') else record
            agent_class = data.get('class', '')

            # Identify post-processor by class name
            if 'PostProcess' in agent_class or agent_class == 'PostProcessAgent':
                postprocessor_records.append(record)
            else:
                main_records.append(record)

        self._logger.debug("Separated records: main=%d, postprocessor=%d",
                         len(main_records), len(postprocessor_records))
        return main_records, postprocessor_records

    def _extract_agent_name(self, records: List[Any], is_main: bool) -> str:
        """
        Extract agent name from records using config mapping.

        Args:
            records: Agent records (DataRecord objects).
            is_main: Whether this is the main agent.

        Returns:
            Agent name from config.
        """
        if not records:
            return "unknown-agent"

        # Look at first LLM record to find agent type
        for record in records:
            data = record.data if hasattr(record, 'data') else record
            agent_class = data.get('class', '')

            # Check if it's a ReAct agent variant
            if 'ReAct' in agent_class or 'react' in agent_class.lower():
                # Find in config by type
                if 'react' in self.agent_name_map:
                    return self.agent_name_map['react']

        # Fallback: extract from config
        for config in self.agent_configs:
            if config.get('kind') == 'agent':
                return config.get('spec', {}).get('name', 'unknown-agent')

        return "unknown-agent"

    def _analyze_agent_records(
        self,
        records: List[Any],
        agent_name: str,
        is_postprocessor: bool = False
    ) -> AgentMetrics:
        """
        Analyze records for a single agent.

        NEW BEHAVIOR: Sums tokens from ALL iterations to get total context across task execution.
        This gives the full token usage for the entire task, not just the final iteration.

        Args:
            records: Records for this agent (DataRecord objects).
            agent_name: Name of the agent (from config).
            is_postprocessor: Whether this is the postprocessor agent.

        Returns:
            AgentMetrics with computed statistics.
        """
        # First pass: collect all LLM records
        llm_records = []
        model_name = "gpt-4"  # default
        llm_name = "unknown-llm"

        for record in records:
            data = record.data if hasattr(record, 'data') else record
            record_type = data.get('type', '')

            if record_type == 'llm':
                llm_records.append(record)

                # Extract model name from config
                config = data.get('config', {})
                if 'model_name' in config:
                    model_name = config['model_name']

                # Extract LLM class to determine LLM name
                llm_class = data.get('class', '')
                if llm_class in self.llm_name_map:
                    llm_name = self.llm_name_map[llm_class]
                elif is_postprocessor and self.postprocessor_llm_name:
                    llm_name = self.postprocessor_llm_name
                else:
                    # Fallback: lookup from agent->llm mapping
                    llm_name = self.agent_llm_map.get(agent_name, "unknown-llm")

        # Count total LLM calls and iterations
        llm_calls = len(llm_records)
        iterations = self._count_iterations(records)

        # NEW: Sum tokens from ALL LLM calls to get total context across all iterations
        input_tokens = 0
        output_tokens = 0

        # Helper function to extract text from response (handles str and dict)
        def extract_response_text(response):
            """Extract text from response, handling both string and dict formats."""
            if response is None:
                return ''
            if isinstance(response, str):
                return response
            if isinstance(response, dict):
                # For function_call agents, response might be a dict with 'content' or 'message'
                # Or it might have the text response directly
                if 'content' in response:
                    content = response['content']
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        # Content might be a list of message parts
                        texts = [str(c) for c in content if c]
                        return ' '.join(texts)
                # Try JSON serialization for structured responses
                try:
                    return json.dumps(response)
                except Exception:  # pylint: disable=broad-except
                    return str(response)
            return str(response)

        if llm_records:
            # Sum tokens from ALL LLM calls (all iterations)
            self._logger.debug("Analyzing %d LLM records for total token count:", llm_calls)

            for i, record in enumerate(llm_records, 1):
                record_data = record.data if hasattr(record, 'data') else record

                # Count input tokens from messages
                messages = record_data.get('messages', [])
                input_text = self._extract_text_from_messages(messages)
                iter_input_tokens = count_tokens(input_text, model=model_name)
                input_tokens += iter_input_tokens

                # Count output tokens from response
                response = record_data.get('response', '')
                response_text = extract_response_text(response)
                iter_output_tokens = count_tokens(response_text, model=model_name)
                output_tokens += iter_output_tokens

                # Log each iteration's tokens
                if response_text:
                    preview = response_text[:60] if len(response_text) > 60 else response_text
                    self._logger.debug(
                        "  Call %d/%d: input=%d tokens, output=%d tokens (%d chars): %s%s",
                        i, llm_calls, iter_input_tokens, iter_output_tokens, len(response_text),
                        preview, "..." if len(response_text) > 60 else ""
                    )
                else:
                    self._logger.debug(
                        "  Call %d/%d: input=%d tokens, output=%d tokens (empty response)",
                        i, llm_calls, iter_input_tokens, iter_output_tokens
                    )

            self._logger.debug(
                "Total across all %d iterations: input=%d tokens, output=%d tokens, total=%d tokens",
                llm_calls, input_tokens, output_tokens, input_tokens + output_tokens
            )
        else:
            self._logger.warning("No LLM records found for agent %s", agent_name)

        # Calculate costs separately for input and output
        input_cost, output_cost = self._calculate_costs(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_name=model_name
        )

        self._logger.debug(
            "Agent %s: iterations=%d, total_input_tokens=%d (all iters), total_output_tokens=%d (all iters), "
            "input_cost=$%.4f, output_cost=$%.4f, total_cost=$%.4f",
            agent_name, iterations, input_tokens, output_tokens, input_cost, output_cost, input_cost + output_cost
        )

        return AgentMetrics(
            agent_name=agent_name,
            llm_name=llm_name,
            model_name=model_name,
            iterations=iterations,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=input_cost + output_cost,
            llm_calls=llm_calls
        )

    def _extract_text_from_messages(self, messages: List[Dict[str, str]]) -> str:
        """
        Extract text content from message list.

        Handles both text content and function_call messages where content may be None.
        """
        text_parts = []
        for msg in messages:
            content = msg.get("content", "")
            # Handle None content (e.g., from function_call messages)
            if content is None:
                content = ""
            text_parts.append(content)
        return " ".join(text_parts)

    def _count_iterations(self, records: List[Any]) -> int:
        """
        Count iterations from records.

        For ReAct agents: count LLM calls that contain action decisions.
        For FunctionCall agents: count LLM calls with tool_calls.
        For post-processor: count refinement iterations.

        Args:
            records: Records to analyze (DataRecord objects).

        Returns:
            Number of iterations.
        """
        iteration_count = 0

        for record in records:
            data = record.data if hasattr(record, 'data') else record
            if data.get('type') == 'llm':
                response = data.get('response', '')

                # Handle None response (e.g., from failed LLM calls)
                if response is None:
                    response = ''

                # Check for ReAct pattern (thought+action or thought+answer)
                if '"thought"' in response and ('"action"' in response or '"answer"' in response):
                    iteration_count += 1
                # Check for FunctionCall pattern (tool_calls in response)
                elif '"tool_calls"' in response or 'tool_calls' in data:
                    iteration_count += 1
                # If neither pattern matches, count as a generic iteration
                elif response:
                    iteration_count += 1

        return max(iteration_count, 1)  # At least 1 iteration

    def _calculate_costs(
        self,
        input_tokens: int,
        output_tokens: int,
        model_name: str
    ) -> Tuple[float, float]:
        """
        Calculate separate input and output costs.

        Args:
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            model_name: Name of the LLM model.

        Returns:
            Tuple of (input_cost, output_cost) in USD.
        """
        # Look up pricing directly by model name
        pricing = self.MODEL_PRICING.get(model_name)

        if pricing is None:
            self._logger.warning(
                "No pricing found for model '%s'. Please add it to MODEL_PRICING in tracer_analyzer.py. "
                "Costs will be set to 0.",
                model_name
            )
            return 0.0, 0.0

        # Calculate costs (pricing is per 1M tokens)
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]

        return input_cost, output_cost
