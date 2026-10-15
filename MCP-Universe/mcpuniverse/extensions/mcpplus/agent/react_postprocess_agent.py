"""
Post-processing agent that produces BOTH direct extraction AND code in a single LLM call.

This agent is cost-optimized:
- ONE LLM call (tool output sent only once as input)
- Generates both: direct extraction text AND Python code
- Executes the code
- Returns both outputs to main agent

Iteration only happens if:
- Output is empty from both methods
- Code execution fails
"""
# pylint: disable=too-many-locals,too-many-return-statements,too-many-branches
# pylint: disable=too-many-statements,broad-exception-caught
import json
from typing import Any, Dict, Optional, Union, List
from dataclasses import dataclass

from mcpuniverse.agent.base import BaseAgent, BaseAgentConfig, AgentResponse
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.common.logger import get_logger
from mcpuniverse.tracer import Tracer
from mcpuniverse.extensions.mcpplus.utils.safe_executor import SafeCodeExecutor  # pylint: disable=no-name-in-module
from mcpuniverse.extensions.mcpplus.utils.stats import count_tokens, PostProcessStats  # pylint: disable=no-name-in-module


@dataclass
class PostProcessAgentConfig(BaseAgentConfig):
    """
    Configuration for PostProcessAgent.

    Attributes:
        max_iterations: Maximum iterations if output is empty or code fails.
        llm_timeout: Timeout for LLM API calls during post-processing.
        skip_iteration_on_size_failure: If True, immediately return original output when both
            extraction methods produce outputs that are too large. If False, retry iteration.
            Default is False (retry).
    """
    max_iterations: int = 3
    llm_timeout: int = 500
    skip_iteration_on_size_failure: bool = False


# Prompt that asks for both extraction and code
DUAL_EXTRACTION_PROMPT = """
You are analyzing tool output to extract specific information. You must provide TWO extraction methods:

1. DIRECT EXTRACTION: Simple text-based extraction of the key information
2. CODE-BASED EXTRACTION: Python code that parses/filters the data

Tool: {tool_name}
{tool_description_section}

Tool Output ({output_length} characters):
{tool_output}

Agent's Goal: {expected_info}

{iteration_history_section}

YOUR TASK:

Provide BOTH extraction methods in JSON format:

{{
  "direct_extraction": "<extracted information as plain text>",
  "code": "<Python code that extracts/filters the data>"
}}

Guidelines:
- **direct_extraction**: Extract and return the relevant information as simple, readable text
- **code**: Write Python code that processes `data` (the tool output) and assigns result to `result` variable
  - The tool output is available as `data` (string)
  - Parse, filter, or transform as needed
  - Assign final output to `result`
  - Keep code concise and focused

{iteration_instruction_section}

Output ONLY valid JSON with both fields. No other text.
""".strip()

class PostProcessAgent(BaseAgent):
    """
    Post-processing agent that produces both direct extraction and code in ONE LLM call.

    Inherits from BaseAgent for automatic tracing integration.
    """

    config_class = PostProcessAgentConfig

    def __init__(
        self,
        llm: BaseLLM,
        safe_executor: SafeCodeExecutor,
        config: Optional[Union[PostProcessAgentConfig, Dict]] = None,
    ):
        """
        Initialize PostProcessAgent.

        Args:
            llm: Language model for extraction.
            safe_executor: Safe code executor.
            config: Configuration dict or object.
        """
        # Convert dict config to PostProcessAgentConfig
        if config is None:
            parsed_config = PostProcessAgentConfig()
        elif isinstance(config, PostProcessAgentConfig):
            parsed_config = config
        elif isinstance(config, dict):
            parsed_config = PostProcessAgentConfig(**config)
        else:
            parsed_config = None

        if parsed_config is not None:
            super().__init__(mcp_manager=None, llm=llm, config=None)
            self._config = parsed_config
            self._name = self._config.name if self._config.name else str(__import__('uuid').uuid4())
            self._config.name = self._name
        else:
            super().__init__(mcp_manager=None, llm=llm, config=config)

        self._safe_executor = safe_executor
        self._logger = get_logger(f"{self.__class__.__name__}:{self._name}")

        # Get model name for token counting
        self._model_name = "gpt-4"
        if hasattr(llm, 'config') and hasattr(llm.config, 'model_name'):
            self._model_name = llm.config.model_name

        self._extraction_prompt = DUAL_EXTRACTION_PROMPT
        self._logger.debug("Using default DUAL_EXTRACTION_PROMPT")

    async def initialize(self):  # pylint: disable=arguments-differ
        """Initialize agent."""
        if self._initialized:
            return
        self._initialized = True

    async def cleanup(self):
        """Cleanup resources."""
        pass  # pylint: disable=unnecessary-pass

    async def _execute(
        self,
        message: Union[str, List[str]],
        **kwargs
    ) -> AgentResponse:
        """
        Execute dual extraction (direct + code) in ONE LLM call.

        Message format is JSON string:
        {
            "tool_name": str,
            "tool_description": str,
            "tool_output": str,
            "expected_info": str
        }

        Returns:
            AgentResponse with both extraction results.
        """
        # Parse input message
        if isinstance(message, list):
            message = message[0] if message else "{}"

        try:
            input_data = json.loads(message)
        except json.JSONDecodeError:
            self._logger.error("Invalid JSON input: %s", message[:200])
            return AgentResponse(
                name=self._name,
                class_name=self.__class__.__name__,
                response="ERROR: Invalid JSON input"
            )

        tool_name = input_data.get("tool_name", "unknown_tool")
        tool_description = input_data.get("tool_description", "")
        tool_output = input_data.get("tool_output", "")
        expected_info = input_data.get("expected_info", "")

        # Get tracer from kwargs (BaseAgent.execute will pass it)
        tracer = kwargs.get("tracer", Tracer())

        self._logger.info(
            "Processing tool=%s, output_length=%d, expected_info=%s",
            tool_name, len(tool_output), expected_info[:100]
        )

        # Run extraction with iteration support
        stats = {
            "postprocessor_iterations": 0,
            "direct_attempts": 0,
            "code_attempts": 0
        }

        result = await self._extract_with_iterations(
            tool_name=tool_name,
            tool_description=tool_description,
            tool_output=tool_output,
            expected_info=expected_info,
            stats=stats,
            tracer=tracer
        )

        # Calculate token counts for stats
        original_tokens = count_tokens(tool_output, model=self._model_name)
        filtered_tokens = count_tokens(result, model=self._model_name)

        # Build PostProcessStats compatible with wrapper_manager
        postprocess_stats = PostProcessStats(
            postprocessor_iterations=stats["postprocessor_iterations"],
            original_chars=len(tool_output),
            filtered_chars=len(result),
            chars_reduced=len(tool_output) - len(result),
            original_tokens=original_tokens,
            filtered_tokens=filtered_tokens,
            tokens_reduced=original_tokens - filtered_tokens,
            success=bool(result and result.strip())
        )

        # Encode stats as JSON in response
        response_data = {
            "filtered_output": result,
            "stats": {
                "postprocessor_iterations": postprocess_stats.postprocessor_iterations,
                "original_chars": postprocess_stats.original_chars,
                "filtered_chars": postprocess_stats.filtered_chars,
                "chars_reduced": postprocess_stats.chars_reduced,
                "original_tokens": postprocess_stats.original_tokens,
                "filtered_tokens": postprocess_stats.filtered_tokens,
                "tokens_reduced": postprocess_stats.tokens_reduced,
                "success": postprocess_stats.success,
            }
        }

        return AgentResponse(
            name=self._name,
            class_name=self.__class__.__name__,
            response=json.dumps(response_data),
            trace_id=tracer.trace_id
        )

    async def _extract_with_iterations(
        self,
        tool_name: str,
        tool_description: str,
        tool_output: str,
        expected_info: str,
        stats: Dict[str, Any],
        tracer
    ) -> str:
        """
        Run dual extraction with iteration support.

        Iterates only if:
        - Both outputs are empty
        - Code execution fails

        Args:
            tool_name: Name of the tool.
            tool_description: Description of the tool.
            tool_output: Output from the tool.
            expected_info: What the agent expects to extract.
            stats: Statistics dict to update.

        Returns:
            Formatted string with both extraction results.
        """
        iteration_history = []

        # Track best partial results across iterations
        best_direct_extraction = ""
        best_code_result = ""
        best_code_error = None

        for iteration in range(self._config.max_iterations):
            stats["postprocessor_iterations"] = iteration + 1
            stats["direct_attempts"] += 1
            stats["code_attempts"] += 1

            self._logger.info("Dual extraction attempt %d/%d", iteration + 1, self._config.max_iterations)

            # Build prompt
            prompt = self._build_prompt(
                tool_name=tool_name,
                tool_description=tool_description,
                tool_output=tool_output,
                expected_info=expected_info,
                iteration_history=iteration_history,
                iteration=iteration
            )

            # Log the full prompt for visibility
            self._logger.info("%s", prompt)

            # Make LLM call with configured timeout and tracing
            try:
                response = await self._llm.generate_async(
                    messages=[{"role": "user", "content": prompt}],
                    tracer=tracer,
                    timeout=self._config.llm_timeout
                )

                # Strip markdown code blocks if present
                response_text = response.strip()
                if response_text.startswith("```"):
                    # Remove first line (```json or ```), and last line (```)
                    lines = response_text.split("\n")
                    if lines[-1].strip() == "```":
                        lines = lines[1:-1]
                    else:
                        lines = lines[1:]
                    response_text = "\n".join(lines)

                # Parse JSON response
                extraction_data = json.loads(response_text)
                direct_extraction = extraction_data.get("direct_extraction", "")
                code = extraction_data.get("code", "")

                self._logger.info("LLM response: %s", response[:200])

            except json.JSONDecodeError as e:
                self._logger.error("Invalid JSON from LLM: %s", str(e))
                iteration_history.append({
                    "iteration": iteration + 1,
                    "direct": "",
                    "code": "",
                    "code_result": "",
                    "error": f"Invalid JSON response: {str(e)}"
                })
                continue
            except Exception as e:
                error_msg = str(e)
                self._logger.error("LLM call failed: %s", error_msg)

                # Check if it's a timeout error
                is_timeout = "timeout" in error_msg.lower() or "timed out" in error_msg.lower()

                if is_timeout:
                    # For timeout, don't add to iteration history (not a wrong approach, just infrastructure issue)
                    # But log it and potentially retry once
                    self._logger.warning("LLM timeout on iteration %d, retrying...", iteration + 1)
                    continue
                # For other errors, add to history
                iteration_history.append({
                    "iteration": iteration + 1,
                    "direct": "",
                    "code": "",
                    "code_result": "",
                    "error": f"LLM error: {error_msg}"
                })
                continue

            # Execute code
            code_result = ""
            code_error = None

            if code:
                try:
                    code_result = str(self._safe_executor.execute(code, tool_output))
                    self._logger.info("Code executed successfully: %d chars", len(code_result))
                except Exception as e:
                    code_error = str(e)
                    self._logger.error("Code execution exception: %s", code_error)

            # Check if we have valid output from BOTH methods
            has_direct = bool(direct_extraction and direct_extraction.strip())
            has_code = bool(code_result and code_result.strip())

            # Track best partial results
            if has_direct:
                best_direct_extraction = direct_extraction
            if has_code:
                best_code_result = code_result
                best_code_error = None  # Clear error if code succeeded
            elif code_error and not best_code_result:
                # Keep track of last error if we never got a successful code result
                best_code_error = code_error

            # Add to history
            iteration_history.append({
                "iteration": iteration + 1,
                "direct": direct_extraction,
                "code": code,
                "code_result": code_result,
                "error": code_error
            })

            # Only return if we have BOTH valid outputs (or no code error)
            # This ensures dual extraction always provides both methods
            if has_direct and has_code:
                # Check size of both outputs (> 50% of input is too large)
                input_tokens = count_tokens(tool_output, model=self._model_name)
                direct_tokens = count_tokens(direct_extraction, model=self._model_name)
                code_output_tokens = count_tokens(code_result, model=self._model_name)
                max_allowed_tokens = int(input_tokens * 0.5)

                direct_too_large = direct_tokens > max_allowed_tokens
                code_too_large = code_output_tokens > max_allowed_tokens

                # If both are too large, decide whether to retry or return original
                if direct_too_large and code_too_large:
                    # Check if we should skip iteration on size failure
                    if self._config.skip_iteration_on_size_failure:
                        self._logger.warning(
                            "⚠️  Both outputs too large: direct=%d tokens, code=%d tokens "
                            "(input: %d, max allowed: %d). skip_iteration_on_size_failure=True, returning original.",
                            direct_tokens, code_output_tokens, input_tokens, max_allowed_tokens
                        )
                        return tool_output

                    # Otherwise, retry if we have iterations left
                    if iteration < self._config.max_iterations - 1:
                        self._logger.warning(
                            "⚠️  Both outputs too large: direct=%d tokens, code=%d tokens "
                            "(input: %d, max allowed: %d). Retrying...",
                            direct_tokens, code_output_tokens, input_tokens, max_allowed_tokens
                        )
                        iteration_history[-1]["error"] = (
                            f"Both direct extraction ({direct_tokens} tokens) and code output "
                            f"({code_output_tokens} tokens) exceed max allowed ({max_allowed_tokens} tokens). "
                            f"Generate more concise extraction and code."
                        )
                        continue
                    # Last iteration and both too large - compare total size vs original
                    self._logger.warning(
                        "⚠️  Last iteration: both outputs too large (direct=%d, code=%d, max=%d). "
                        "Comparing filtered vs original size...",
                        direct_tokens, code_output_tokens, max_allowed_tokens
                    )
                    # Calculate what we'd return if we use filtered output
                    filtered_output = self._format_output(direct_extraction, code_result, None)
                    filtered_total_tokens = count_tokens(filtered_output, model=self._model_name)

                    if filtered_total_tokens < input_tokens:
                        self._logger.info(
                            "Filtered output (%d tokens) smaller than original (%d tokens), using filtered",
                            filtered_total_tokens, input_tokens
                        )
                        return filtered_output
                    self._logger.warning(
                        "Filtered output (%d tokens) larger than original (%d tokens), returning original",
                        filtered_total_tokens, input_tokens
                    )
                    return tool_output

                # Determine which outputs to include based on size
                use_direct = has_direct and not direct_too_large
                use_code = has_code and not code_too_large

                if direct_too_large:
                    self._logger.warning(
                        "⚠️  Direct extraction too large (%d tokens > %d allowed), excluding from output",
                        direct_tokens, max_allowed_tokens
                    )
                if code_too_large:
                    self._logger.warning(
                        "⚠️  Code output too large (%d tokens > %d allowed), excluding from output",
                        code_output_tokens, max_allowed_tokens
                    )

                # If we excluded everything, that's a problem - shouldn't happen but handle it
                if not use_direct and not use_code:
                    self._logger.error("Both outputs excluded due to size, this shouldn't happen")
                    # Fallback: continue iteration or return original
                    if iteration < self._config.max_iterations - 1:
                        continue
                    return tool_output

                # Success! Return output (possibly excluding oversized parts)
                final_direct = direct_extraction if use_direct else ""
                final_code_result = code_result if use_code else ""

                if use_direct and use_code:
                    self._logger.info("✓ Both extraction methods succeeded and passed size check")
                elif use_direct:
                    self._logger.info("✓ Direct extraction succeeded (code output excluded due to size)")
                else:
                    self._logger.info("✓ Code extraction succeeded (direct extraction excluded due to size)")

                return self._format_output(
                    direct_extraction=final_direct,
                    code_result=final_code_result,
                    code_error=None
                )

            # At least one method failed - log and continue iterating
            if not has_direct and not has_code:
                self._logger.warning("Iteration %d: both outputs empty, retrying...", iteration + 1)
            elif not has_direct:
                self._logger.warning("Iteration %d: direct extraction empty, retrying...", iteration + 1)
            elif not has_code:
                self._logger.warning("Iteration %d: code execution failed (%s), retrying...",
                                   iteration + 1, code_error or "empty result")

        # All iterations exhausted - return best partial results we got
        if best_direct_extraction or best_code_result:
            # We have at least some partial success - return it
            self._logger.warning(
                "All %d iterations exhausted. Returning best partial results: "
                "direct=%s, code=%s",
                self._config.max_iterations,
                "yes" if best_direct_extraction else "no",
                "yes" if best_code_result else "no"
            )

            return self._format_output(
                direct_extraction=best_direct_extraction,
                code_result=best_code_result,
                code_error=best_code_error if not best_code_result else None
            )
        # Complete failure - return original unprocessed tool output
        self._logger.error(
            "All %d iterations exhausted with no valid results from either method. "
            "Returning original tool output.",
            self._config.max_iterations
        )
        return tool_output

    def _build_prompt(
        self,
        tool_name: str,
        tool_description: str,
        tool_output: str,
        expected_info: str,
        iteration_history: List[Dict],
        iteration: int
    ) -> str:
        """Build the extraction prompt."""
        # Tool description section
        if tool_description:
            tool_description_section = f"Description: {tool_description}"
        else:
            tool_description_section = ""

        # Iteration history section
        if iteration_history:
            history_lines = ["\nPREVIOUS ATTEMPTS:"]
            for hist in iteration_history:
                history_lines.append(f"\nAttempt {hist['iteration']}:")
                if hist.get('error'):
                    history_lines.append(f"  Error: {hist['error']}")
                if hist.get('direct'):
                    history_lines.append(f"  Direct: {hist['direct'][:100]}...")
                if hist.get('code'):
                    history_lines.append(f"  Code: {hist['code'][:100]}...")
                if hist.get('code_result'):
                    history_lines.append(f"  Result: {hist['code_result'][:100]}...")
            iteration_history_section = "\n".join(history_lines)
        else:
            iteration_history_section = ""

        # Iteration instruction
        if iteration > 0:
            iteration_instruction_section = "\nIMPORTANT: Previous attempt(s) failed. Try a different approach."
        else:
            iteration_instruction_section = ""

        return self._extraction_prompt.format(
            tool_name=tool_name,
            tool_description_section=tool_description_section,
            tool_output=tool_output,
            output_length=len(tool_output),
            expected_info=expected_info,
            iteration_history_section=iteration_history_section,
            iteration_instruction_section=iteration_instruction_section
        )

    def _format_output(
        self,
        direct_extraction: str,
        code_result: str,
        code_error: Optional[str]
    ) -> str:
        """Format the final output with both results."""
        lines = []
        lines.append("=" * 25)
        lines.append("DUAL EXTRACTION RESULTS")
        lines.append("=" * 25)
        lines.append("")
        lines.append("Two extraction methods were used. You can use either result,")
        lines.append("or combine information from both as appropriate.")
        lines.append("")

        # Direct extraction
        lines.append("-" * 25)
        lines.append("DIRECT EXTRACTION:")
        lines.append("-" * 25)
        if direct_extraction:
            lines.append(direct_extraction)
        else:
            lines.append("(No output)")
        lines.append("")

        # Code-based extraction
        lines.append("-" * 25)
        lines.append("CODE-BASED EXTRACTION:")
        lines.append("-" * 25)
        if code_error:
            lines.append(f"ERROR: {code_error}")
        elif code_result:
            lines.append(code_result)
        else:
            lines.append("(No output)")
        lines.append("")

        lines.append("=" * 25)

        return "\n".join(lines)
