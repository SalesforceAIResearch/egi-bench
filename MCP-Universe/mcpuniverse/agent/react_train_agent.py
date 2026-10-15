"""
A ReAct agent implementation for training with Qwen3 models.

This agent uses raw prompt format with Qwen3 chat template for vLLM inference,
designed for training and evaluation purposes.
"""
# pylint: disable=broad-exception-caught
import asyncio
import os
import json
from typing import Optional, Union, Dict, List, Any
from collections import OrderedDict
from dataclasses import dataclass

try:
    from google import genai
    from google.genai import types as genai_types
    from google.oauth2 import credentials as oauth2_credentials
except ImportError:
    genai = None
    genai_types = None
    oauth2_credentials = None

from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.common.logger import get_logger
from mcpuniverse.tracer import Tracer
from mcpuniverse.callbacks.base import (
    send_message,
    send_message_async,
    CallbackMessage,
    MessageType,
)
from .base import BaseAgentConfig, BaseAgent
from .utils import (
    get_tools_description,
    parse_qwen3_react_response,
)
from .types import AgentResponse

DEFAULT_CONFIG_FOLDER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "configs")


@dataclass
class ReActTrainConfig(BaseAgentConfig):
    """
    Configuration class for ReAct training agents.

    Attributes:
        system_prompt (str): The system prompt template file or string.
        max_iterations (int): Maximum number of reasoning iterations.
        summarize_tool_response (bool): Whether to summarize tool responses using the LLM.
        reject_long_response (bool): If True, reject long responses instead of summarizing,
            prompting the model to use smarter/more specific tool calls.
        tool_result_max_length (int): Maximum length of tool result before summarization/rejection.
        summarizer_type (str): Type of summarizer to use: "gemini" or "self" (use rollout model).
        summarizer_model (str): Gemini model to use for summarization (only used when summarizer_type="gemini").
        summarizer_gcp_project (str): GCP project for Vertex AI (only used when summarizer_type="gemini").
        summarizer_max_rounds (int): Maximum rounds of recursive summarization if result is still too long.
        token_limit (int): Maximum token count before early termination of the trajectory.
    """
    system_prompt: str = os.path.join(DEFAULT_CONFIG_FOLDER, "react_prompt.j2")
    max_iterations: int = 5
    summarize_tool_response: bool = False
    reject_long_response: bool = False  # If True, reject long responses instead of summarizing
    tool_result_max_length: int = 2000
    summarizer_type: str = "gemini"  # "gemini" or "self"
    summarizer_model: str = "gemini-3-flash-preview"
    summarizer_gcp_project: str = "salesforce-research-internal"
    summarizer_max_rounds: int = 3  # max rounds of recursive summarization
    token_limit: int = 80000


class ReActTrain(BaseAgent):
    """
    ReAct agent implementation for training with Qwen3 models.

    This class implements the ReAct agent using raw prompt format with Qwen3 chat template,
    designed to work with vLLM inference backend for training and evaluation.

    Attributes:
        config_class (Type[ReActTrainConfig]): The configuration class for this agent.
        alias (List[str]): Alternative names for this agent type.
    """
    config_class = ReActTrainConfig
    alias = ["react_train", "react_qwen3"]

    def __init__(
        self,
        mcp_manager: MCPManager,
        llm: BaseLLM,
        config: Optional[Union[Dict, str]] = None,
        tokenizer: Optional[Any] = None,
    ):
        """
        Initialize a ReAct training agent.

        Args:
            mcp_manager (MCPManager): An MCP server manager for handling tool interactions.
            llm (BaseLLM): A language model for generating responses.
            config (Optional[Union[Dict, str]]): Agent configuration as a dictionary or file path.
            tokenizer (Optional[Any]): Tokenizer for checking token count (optional).
        """
        super().__init__(mcp_manager=mcp_manager, llm=llm, config=config)
        self._logger = get_logger(f"{self.__class__.__name__}:{self._name}")
        self._history: List[Dict[str, Any]] = []
        self._tools_description = ""
        self._message = ""
        self._raw_prompt = ""  # Accumulated raw prompt text
        self._tokenizer = tokenizer  # Tokenizer for checking token count
        self._gemini_client = None  # Cached Gemini client

    def set_tokenizer(self, tokenizer):
        """Set the tokenizer used for token count checking."""
        self._tokenizer = tokenizer

    async def _initialize(self):
        """Initialize the agent after tools are loaded."""
        if self._tools:
            self._tools_description = get_tools_description(self._tools)

    async def _get_gemini_client(self):
        """Get or create a cached Gemini client using gcloud credentials."""
        if self._gemini_client is not None:
            return self._gemini_client

        if genai is None:
            raise ImportError(
                "google-genai is required for Gemini summarization. "
                "Install it with: pip install google-genai google-auth"
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                'gcloud', 'auth', 'print-access-token',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError("gcloud auth failed")
            access_token = stdout.decode().strip()
            user_credentials = oauth2_credentials.Credentials(token=access_token)

            self._gemini_client = genai.Client(
                vertexai=True,
                project=self._config.summarizer_gcp_project,
                location='global',
                credentials=user_credentials
            )
        except Exception as e:
            self._logger.warning("Could not get user credentials: %s, using default credentials", str(e))
            self._gemini_client = genai.Client(
                vertexai=True,
                project=self._config.summarizer_gcp_project,
                location='global'
            )
        return self._gemini_client

    async def _summarize_tool_result(self, tool_result: str, action: Dict[str, Any]) -> str:
        """
        Summarize a long tool result using LLM.

        Args:
            tool_result: The original tool result to summarize.
            action: The action that produced this result (for context).

        Returns:
            str: The summarized tool result.
        """
        if not self._config.summarize_tool_response:
            return tool_result

        if len(tool_result) <= self._config.tool_result_max_length:
            return tool_result

        # Build context from history
        history_context = ""
        if self._history:
            recent_history = self._history[-3:]  # Last 3 steps
            for h in recent_history:
                if "thought" in h:
                    history_context += f"Thought: {h['thought']}\n"
                if "action" in h:
                    history_context += f"Action: {json.dumps(h['action'])}\n"

        system_prompt = (
            "You are a helpful assistant that summarizes tool results concisely. "
            "The summary MUST be under 500 words."
        )

        # Recursive summarization loop
        current_result = tool_result
        original_length = len(tool_result)
        total_rounds = 0

        for round_num in range(self._config.summarizer_max_rounds):
            if len(current_result) <= self._config.tool_result_max_length:
                break  # Result is short enough, stop summarizing

            total_rounds += 1

            # Build prompt for this round
            if round_num == 0:
                # First round: include full context
                args_json = json.dumps(action.get('arguments', {}))
                user_prompt = (
                    f"You are a helpful assistant that summarizes "
                    f"tool execution results.\n\n"
                    f"Current task: {self._message}\n\n"
                    f"Recent reasoning history:\n{history_context}\n\n"
                    f"The following tool was just called:\n"
                    f"- Server: {action.get('server', 'unknown')}\n"
                    f"- Tool: {action.get('tool', 'unknown')}\n"
                    f"- Arguments: {args_json}\n\n"
                    f"Tool result (very long, needs summarization):\n"
                    f"{current_result}\n\n"
                    f"Please summarize the above tool result concisely "
                    f"while preserving all important information that "
                    f"would be needed to answer the user's question. "
                    f"Keep key data points, numbers, dates, and "
                    f"relevant facts. The summary should be under "
                    f"500 words."
                )
            else:
                # Subsequent rounds: just ask to summarize further
                max_len = self._config.tool_result_max_length
                user_prompt = (
                    f"The following text is still too long "
                    f"(currently {len(current_result)} characters, "
                    f"target is under {max_len} characters).\n\n"
                    f"Please summarize it further while preserving "
                    f"the most important information:\n\n"
                    f"{current_result}\n\n"
                    f"Make the summary shorter and more concise. "
                    f"Keep only the essential facts."
                )

            try:
                if self._config.summarizer_type == "self":
                    summarized = await self._summarize_with_self_llm(system_prompt, user_prompt)
                else:
                    summarized = await self._summarize_with_gemini(system_prompt, user_prompt)

                self._logger.info(
                    "Summarize round %d: %d -> %d characters (using %s)",
                    round_num + 1, len(current_result), len(summarized), self._config.summarizer_type
                )

                # Check if summarization actually reduced the length
                if len(summarized) >= len(current_result):
                    self._logger.warning("Summarization did not reduce length, stopping")
                    break

                current_result = summarized

            except Exception as e:
                self._logger.warning("Failed to summarize in round %d: %s", round_num + 1, str(e))
                break

        # Final result
        if total_rounds > 0:
            return (
                f"[Summarized from {original_length} chars "
                f"in {total_rounds} rounds]\n{current_result}"
            )
        return current_result

    async def _summarize_with_gemini(self, system_prompt: str, user_prompt: str) -> str:
        """Summarize using Gemini API."""
        client = await self._get_gemini_client()

        for try_count in range(3):
            try:
                response = client.models.generate_content(
                    model=self._config.summarizer_model,
                    contents=user_prompt,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=system_prompt,
                    )
                )
                return response.text
            except Exception as e:
                self._logger.warning("Gemini API error (attempt %d): %s", try_count + 1, str(e))
                await asyncio.sleep(5)

        raise RuntimeError("All Gemini API retries failed")

    async def _summarize_with_self_llm(self, system_prompt: str, user_prompt: str) -> str:
        """
        Summarize using the rollout model (self._llm).
        Uses raw prompt format (ChatML) like the main agent.
        """
        # Build raw prompt in ChatML format (same as the main agent)
        raw_prompt = (
            f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
            f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

        # Use raw format like the main agent
        messages = [{"role": "raw", "content": raw_prompt}]

        # Use the same LLM that's used for rollout
        response = await self._llm.generate_async(messages=messages)

        if response is None:
            raise RuntimeError("Self LLM returned None")

        return response

    def _build_system_instruction(self, _question: str, output_format: Optional[Union[str, Dict]] = None) -> str:
        """
        Build the system instruction for the agent.

        Args:
            question: The user's question
            output_format: Optional output format specification

        Returns:
            str: The system instruction
        """
        instruction = f"""{self._config.instruction}

Your goal is to reason about the task and use tools to answer it accurately.
Please use only the tools that are explicitly defined below.
At each step, you can either use a tool or provide a final answer.
Do **not** ask clarifying questions.
Your MUST output the final answer within {self._config.max_iterations} steps. Be aware of the number of steps remaining.

Instructions:
1. Analyze the query, previous reasoning steps, and results.
2. Decide on the next action: use a tool or provide a final answer.
3. Respond in the following JSON format:

If you need to use a tool:
```json
{{
    "thought": "Your detailed reasoning about what to do next",
    "action": {{
        "reason": "Explanation of why you chose this tool",
        "server": "server-name",
        "tool": "tool-name",
        "arguments": {{
            "argument-name": "argument-value"
        }}
    }}
}}
```

If you have enough information to answer the query:
```json
{{
    "thought": "Your final reasoning process to derive the answer.",
    "answer": "Final answer to the query"
}}
```
"""
        if output_format is not None:
            instruction += "\n\n" + self._get_output_format_prompt(output_format)
        else:
            instruction += """
Remember:
- Be thorough in your reasoning.
- Use tools when you need more information.
- Always base your reasoning on the actual results from tool use.
- If a tool returns no results or fails, acknowledge this and consider using a different tool or approach.
- Provide a final answer when you're confident you have sufficient information.
- The response must be in a valid JSON format. Do not wrap in code fences.
"""
        return instruction.strip()

    def _build_initial_prompt(self, question: str, output_format: Optional[Union[str, Dict]] = None) -> str:
        """
        Construct the initial prompt in Qwen3 chat template format (without history).

        Args:
            question (str): The user's question or task.
            output_format: Optional output format specification

        Returns:
            str: The initial prompt in Qwen3 chat template format.
        """
        system_instruction = self._build_system_instruction(question, output_format)

        parts: List[str] = []

        # System message
        parts.append("<|im_start|>system\n")
        parts.append(system_instruction.strip())
        if self._tools_description:
            parts.append("\n\n")
            parts.append(self._tools_description.strip())
        parts.append("<|im_end|>\n")

        # User message
        parts.append("<|im_start|>user\n")
        parts.append(question.strip())
        parts.append("<|im_end|>\n")

        # Start of assistant's response
        parts.append("<|im_start|>assistant\n")

        return "".join(parts)

    async def _check_token_limit(
        self, iter_num: int, tracer: Tracer, callbacks: list,
    ) -> Optional[AgentResponse]:
        """Check if the token limit has been exceeded.

        Returns an AgentResponse if the limit is exceeded, otherwise None.
        """
        if self._tokenizer is None:
            return None
        try:
            prompt_tokens = self._tokenizer.encode(
                self._raw_prompt, add_special_tokens=False,
            )
            if len(prompt_tokens) <= self._config.token_limit:
                return None

            self._logger.warning(
                "[Token Limit] Total tokens (%d) exceeds %d threshold, "
                "ending trajectory early at iteration %d",
                len(prompt_tokens), self._config.token_limit,
                iter_num + 1,
            )
            token_limit_msg = (
                "I'm sorry, but I couldn't find a satisfactory "
                "answer within the allowed max number of tokens."
            )
            await self._send_callback_message(
                callbacks=callbacks,
                iter_num=iter_num,
                thought="Token limit exceeded",
                answer=token_limit_msg,
            )
            return AgentResponse(
                name=self._name,
                class_name=self.__class__.__name__,
                response=token_limit_msg,
                trace_id=tracer.trace_id,
            )
        except Exception as e:
            self._logger.warning(
                "Failed to check token count: %s, continuing...", e,
            )
        return None

    async def _execute_tool_action(
        self, action: Dict[str, Any], tracer: Tracer, callbacks: list,
    ) -> str:
        """Execute a tool action and return the (possibly processed) result."""
        if (
            not isinstance(action, dict)
            or "server" not in action
            or "tool" not in action
        ):
            return "Invalid action format"

        try:
            tool_result_obj = await self.call_tool(
                action, tracer=tracer, callbacks=callbacks,
            )
            tool_result = tool_result_obj.content[0].text

            # Handle long tool results
            if len(tool_result) > self._config.tool_result_max_length:
                if self._config.reject_long_response:
                    max_len = self._config.tool_result_max_length
                    return (
                        f"[RESULT TOO LONG] The tool returned "
                        f"{len(tool_result)} characters, which "
                        f"exceeds the limit of {max_len} characters. "
                        f"Please use more specific parameters to "
                        f"narrow down the results. For example, use "
                        f"a specific date instead of a date range, "
                        f"or filter by specific criteria to reduce "
                        f"the response size."
                    )
                if self._config.summarize_tool_response:
                    tool_result = await self._summarize_tool_result(
                        tool_result, action,
                    )
            return tool_result
        except Exception as e:
            return f"Error calling tool: {str(e)[:500]}"

    async def _execute(
        self,
        message: Union[str, List[str]],
        output_format: Optional[Union[str, Dict]] = None,
        **kwargs,
    ) -> AgentResponse:
        """
        Execute the ReAct agent's reasoning and action loop.

        This method processes the user's message, generates thoughts and actions,
        and returns a final answer or explanation.

        Uses raw prompt accumulation instead of reconstructing from history.

        Args:
            message (Union[str, List[str]]): The user's message or a list of messages.
            output_format (Optional[Union[str, Dict]]): Desired format for the output.
            **kwargs: Additional keyword arguments.

        Returns:
            AgentResponse: The agent's final response, including the answer and trace information.
        """
        if isinstance(message, (list, tuple)):
            message = "\n".join(message)
        self._message = message

        tracer = kwargs.get("tracer", Tracer())
        callbacks = kwargs.get("callbacks", [])

        format_error_count = 0

        # Build initial prompt only once (system + tools + user + assistant start)
        self._raw_prompt = self._build_initial_prompt(message, output_format)

        for iter_num in range(self._config.max_iterations):
            try:
                # Check token count before generating response
                limit_resp = await self._check_token_limit(
                    iter_num, tracer, callbacks,
                )
                if limit_resp is not None:
                    return limit_resp

                messages = [{"role": "raw", "content": self._raw_prompt}]

                # Generate response using the LLM
                response = await self._llm.generate_async(
                    messages=messages,
                    tracer=tracer,
                    callbacks=callbacks,
                )

                if response is None or response == '{}':
                    self._logger.warning(
                        "[DEBUG] Response is None or empty: %r", response,
                    )
                    continue

                # Parse the response
                parsed_response = parse_qwen3_react_response(response)

                # Check for parsing errors
                if "error" in parsed_response:
                    format_error_count += 1
                    self._logger.warning(
                        "Failed to parse response (attempt %d): %s",
                        format_error_count,
                        parsed_response["error"]
                    )
                    self._logger.warning(
                        "[DEBUG] Full raw response for parsing error:\n%s",
                        response,
                    )

                    if format_error_count <= 3:
                        # Append raw response and error feedback to raw prompt
                        error_msg = (
                            "Previous response could not be parsed as "
                            f"JSON. Error: {parsed_response['error']}\n"
                            f"Raw response: {parsed_response['raw'][:200]}"
                            "...\n\nPlease respond with valid JSON format."
                        )
                        self._raw_prompt += f"{response}<|im_end|>\n"
                        self._raw_prompt += (
                            f"<|im_start|>user\n{error_msg}<|im_end|>\n"
                        )
                        self._raw_prompt += "<|im_start|>assistant\n"

                        self._history.append({
                            "thought": "JSON parsing error occurred",
                            "result": error_msg,
                        })
                        continue

                    # Give up and return the raw response
                    await self._send_callback_message(
                        callbacks=callbacks,
                        iter_num=iter_num,
                        thought="Multiple parsing errors occurred",
                        answer=parsed_response["raw"],
                    )
                    return AgentResponse(
                        name=self._name,
                        class_name=self.__class__.__name__,
                        response=parsed_response["raw"],
                        trace_id=tracer.trace_id,
                    )

                # Handle final answer
                if parsed_response["answer"] is not None:
                    self._raw_prompt += f"{response}<|im_end|>\n"

                    self._history.append({
                        "thought": parsed_response["thought"],
                        "answer": parsed_response["answer"],
                    })

                    await self._send_callback_message(
                        callbacks=callbacks,
                        iter_num=iter_num,
                        thought=parsed_response["thought"],
                        answer=parsed_response["answer"],
                    )

                    return AgentResponse(
                        name=self._name,
                        class_name=self.__class__.__name__,
                        response=parsed_response["answer"],
                        trace_id=tracer.trace_id,
                    )

                # Handle tool action
                if parsed_response["action"]:
                    action = parsed_response["action"]
                    tool_result = await self._execute_tool_action(
                        action, tracer, callbacks,
                    )

                    # Append raw response + tool result to raw prompt
                    self._raw_prompt += f"{response}<|im_end|>\n"
                    self._raw_prompt += (
                        "<|im_start|>user\n"
                        f"Tool execution result:\n{tool_result}"
                        "<|im_end|>\n"
                    )
                    self._raw_prompt += "<|im_start|>assistant\n"

                    self._history.append({
                        "thought": parsed_response["thought"],
                        "action": action,
                        "result": tool_result,
                    })

                    display_result = (
                        tool_result[:500] + "..."
                        if len(tool_result) > 500
                        else tool_result
                    )
                    await self._send_callback_message(
                        callbacks=callbacks,
                        iter_num=iter_num,
                        thought=parsed_response["thought"],
                        action=action,
                        result=display_result,
                    )
                else:
                    # No action and no answer - format error
                    format_error_count += 1
                    if format_error_count <= 3:
                        error_msg = (
                            "Response must contain either 'action' or "
                            "'answer' field. Please provide a valid "
                            "response."
                        )
                        self._raw_prompt += f"{response}<|im_end|>\n"
                        self._raw_prompt += (
                            f"<|im_start|>user\n{error_msg}<|im_end|>\n"
                        )
                        self._raw_prompt += "<|im_start|>assistant\n"

                        self._history.append({
                            "thought": parsed_response["thought"],
                            "result": error_msg,
                        })
                        await self._send_callback_message(
                            callbacks=callbacks,
                            iter_num=iter_num,
                            thought=(
                                parsed_response["thought"]
                                + "\n\n" + error_msg
                            ),
                        )
                    else:
                        # Give up and use thought as answer
                        await self._send_callback_message(
                            callbacks=callbacks,
                            iter_num=iter_num,
                            answer=parsed_response["thought"],
                        )
                        return AgentResponse(
                            name=self._name,
                            class_name=self.__class__.__name__,
                            response=parsed_response["thought"],
                            trace_id=tracer.trace_id,
                        )

            except Exception as e:
                self._logger.error(
                    "Failed to process response: %s", str(e),
                )
                error_response = f"Error: {str(e)}"
                self._history.append({
                    "thought": "An error occurred",
                    "result": error_response,
                })
                await self._send_callback_message(
                    callbacks=callbacks,
                    iter_num=iter_num,
                    thought=error_response,
                )

        return AgentResponse(
            name=self._name,
            class_name=self.__class__.__name__,
            response=(
                "I'm sorry, but I couldn't find a satisfactory "
                "answer within the allowed number of iterations."
            ),
            trace_id=tracer.trace_id,
        )

    def clear_history(self):
        """
        Clear the agent's conversation history.
        """
        self._history = []

    def reset(self):
        """Reset the agent."""
        self.clear_history()
        self._raw_prompt = ""

    @staticmethod
    async def _send_callback_message(
        callbacks,
        iter_num: int,
        thought: str = "",
        action: Union[str, Dict] = "",
        result: str = "",
        answer: str = "",
    ):
        """Send log messages."""
        logs = []
        if thought:
            logs.append(("thought", thought))
        if action:
            action_str = json.dumps(action, indent=2) if isinstance(action, dict) else str(action)
            logs.append(("action", action_str))
        if result:
            logs.append(("result", result))
        if answer:
            logs.append(("answer", answer))

        data = OrderedDict({"Iteration": iter_num + 1})
        for tag, value in logs:
            data[tag] = value
        send_message(
            callbacks,
            message=CallbackMessage(
                source=__file__,
                type=MessageType.LOG,
                data=data,
            ),
        )
        data = [
            f"{'=' * 66}\n",
            f"Iteration: {iter_num + 1}\n",
            f"{'-' * 66}\n",
        ]
        for tag, value in logs:
            data.append(f"\033[32m{tag.capitalize()}: {value}\n\n\033[0m")
        await send_message_async(
            callbacks,
            message=CallbackMessage(
                source=__file__,
                type=MessageType.LOG,
                metadata={
                    "event": "plain_text",
                    "data": "".join(data),
                },
            ),
        )

    @staticmethod
    def _get_output_format_prompt(output_format: Union[str, Dict]) -> str:
        """Return the custom output-format prompt for ReAct agent."""
        custom_output_format_prompt = """
Follow this JSON format when you output the final answer:
{output_format}
No markdown formatting. No extra text. Do not include any literal such as json before the output. Do not wrap in code fences.
Property names must be enclosed in double quotes.
""".strip()

        if isinstance(output_format, dict):
            output_format_prompt = custom_output_format_prompt.format(
                output_format=json.dumps(output_format, indent=2)
            )
        else:
            output_format_prompt = output_format
        return output_format_prompt.strip()
