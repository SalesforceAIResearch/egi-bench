"""
Gemini LLMs
"""
# pylint: disable=broad-exception-caught
import os
import base64
import json
import uuid
import time
import logging
import traceback
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type, Union

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.types import Content, FunctionCall, Part
from pydantic import BaseModel as PydanticBaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.context import Context

from .base import BaseLLM

load_dotenv()


@dataclass
class GeminiConfig(BaseConfig):
    """
    Configuration for Gemini language models.

    Attributes:
        model_name (str): The name of the Gemini model to use (default: "gemini-2.0-flash").
        api_key (str): The Gemini API key (default: environment variable GEMINI_API_KEY).
        temperature (float): Controls randomness in output (default: 1.0).
        top_p (float): Controls diversity of output (default: 1.0).
        frequency_penalty (float): Penalizes frequent token use (default: 0.0).
        presence_penalty (float): Penalizes repeated topics (default: 0.0).
        max_completion_tokens (int): Maximum number of tokens in the completion (default: 2048).
        seed (int): Random seed for reproducibility (default: 12345).
    """
    model_name: str = "gemini-2.5-flash"
    api_key: str = os.getenv("GEMINI_API_KEY", "")
    temperature: float = 1.0
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_completion_tokens: int = 10000
    seed: int = 12345


class GeminiModel(BaseLLM):
    """
    Gemini language models.

    This class provides methods to interact with Gemini's language models,
    including generating responses based on input messages.

    Attributes:
        config_class (Type[GeminiConfig]): Configuration class for the model.
        alias (str): Alias for the model, used for identification.
    """
    config_class = GeminiConfig
    alias = "gemini"
    env_vars = ["GEMINI_API_KEY"]

    def __init__(self, config: Optional[Union[Dict, str]] = None):
        super().__init__()
        self.config = GeminiModel.config_class.load(config)

    def _generate(
            self,
            messages: List[dict[str, str]],
            response_format: Type[PydanticBaseModel] = None,
            **kwargs
    ):
        """
        Generates content using the Gemini model.

        Args:
            messages (List[dict[str, str]]): List of message dictionaries,
                each containing 'role' and 'content' keys.
            response_format (Type[PydanticBaseModel], optional): Pydantic model
                defining the structure of the desired output. If None, generates
                free-form text.
            **kwargs: Additional keyword arguments including:
                - max_retries (int): Maximum number of retry attempts (default: 5)
                - base_delay (float): Base delay in seconds for exponential backoff (default: 10.0)
                - timeout (int): Request timeout in seconds (default: 30)

        Returns:
            Union[str, PydanticBaseModel, None]: Generated content as a string
                if no response_format is provided, a Pydantic model instance if
                response_format is provided, or None if parsing structured output fails.
                Returns None if all retry attempts fail or non-retryable errors occur.
        """
        max_retries = kwargs.get("max_retries", 5)
        base_delay = kwargs.get("base_delay", 10.0)

        for attempt in range(max_retries + 1):
            try:
                client = genai.Client(api_key=self.config.api_key)
                system_message, formatted_messages = self._create_gemini_style_messages(messages)

                config_dict = {
                    "http_options": types.HttpOptions(
                        timeout=int(kwargs.get("timeout", 300)) * 1000
                    ),
                    "system_instruction": system_message,
                    "temperature": self.config.temperature,
                    "top_p": self.config.top_p,
                    "frequency_penalty": self.config.frequency_penalty,
                    "presence_penalty": self.config.presence_penalty,
                    "max_output_tokens": self.config.max_completion_tokens,
                    "seed": self.config.seed,
                    "thinking_config": types.ThinkingConfig(
                        include_thoughts=True,
                    )
                }

                # Handle tools if provided - convert from OpenAI format to Gemini format
                if 'tools' in kwargs:
                    gemini_tools = self._convert_openai_tools_to_gemini(kwargs['tools'])
                    if gemini_tools:
                        config_dict["tools"] = gemini_tools

                # Add response_schema only if response_format is provided
                if response_format is not None:
                    config_dict["response_schema"] = response_format

                config = types.GenerateContentConfig(**config_dict)

                # # Ensure we have content to send
                chat = client.models.generate_content(
                    model=self.config.model_name,
                    config=config,
                    contents=formatted_messages
                )
                # If tools are provided, return a response object similar to OpenAI's format
                if 'tools' in kwargs:
                    return self._create_openai_style_response(chat)

                # For backward compatibility, return just content when no tools
                if response_format is None:
                    return chat.text
                return chat.parsed

            except Exception as e:
                # Check if this is a retryable error
                error_str = str(e).lower()
                is_retryable = any(keyword in error_str for keyword in [
                    'rate limit', 'quota', 'timeout', 'connection', 'network',
                    'service unavailable', 'internal error', '429', '500', '502', '503', '504'
                ])

                if not is_retryable or attempt == max_retries:
                    # Last attempt failed or non-retryable error, return None instead of raising
                    if attempt == max_retries:
                        logging.warning("All %d attempts failed. Error: %s", max_retries + 1, e)
                    else:
                        logging.error("Non-retryable error occurred: %s", e)
                        traceback.print_exc()
                    return None

                # Calculate delay with exponential backoff
                delay = base_delay * (2 ** attempt)
                logging.info("Attempt %d failed with error: %s. Retrying in %.1f seconds...",
                           attempt + 1, e, delay)
                time.sleep(delay)

    def _convert_openai_tools_to_gemini(self, openai_tools: List[dict]) -> List[types.Tool]:
        """
        Convert OpenAI format tools to Gemini format.
        
        OpenAI format:
        {
            "type": "function",
            "function": {
                "name": "function_name",
                "description": "function description",
                "parameters": {...}
            }
        }
        
        Gemini format:
        Tool(function_declarations=[FunctionDeclaration(...)])
        """
        gemini_tools = []
        function_declarations = []

        for tool in openai_tools:
            if tool.get("type") == "function" and "function" in tool:
                func_def = tool["function"]

                # Convert parameters schema
                parameters_schema = func_def.get("parameters", {})
                gemini_schema = self._convert_openai_schema_to_gemini(parameters_schema)

                func_decl = types.FunctionDeclaration(
                    name=func_def["name"],
                    description=func_def.get("description", ""),
                    parameters=gemini_schema
                )
                function_declarations.append(func_decl)

        if function_declarations:
            gemini_tools.append(types.Tool(function_declarations=function_declarations))

        return gemini_tools

    def _convert_openai_schema_to_gemini(self, openai_schema: dict) -> types.Schema:
        """
        Convert OpenAI JSON schema to Gemini Schema format.
        """
        if not openai_schema:
            return types.Schema(type="object")

        schema_dict = {
            "type": openai_schema.get("type", "object")
        }

        if "properties" in openai_schema:
            properties = {}
            for prop_name, prop_def in openai_schema["properties"].items():
                properties[prop_name] = self._convert_openai_schema_to_gemini(prop_def)
            schema_dict["properties"] = properties

        if "required" in openai_schema:
            schema_dict["required"] = openai_schema["required"]

        if "description" in openai_schema:
            schema_dict["description"] = openai_schema["description"]

        if "items" in openai_schema:
            schema_dict["items"] = self._convert_openai_schema_to_gemini(openai_schema["items"])

        return types.Schema(**schema_dict)

    def _create_openai_style_response(self, gemini_response):
        """
        Create an OpenAI-style response object from Gemini's response.
        
        Args:
            gemini_response: The raw response from Gemini
            
        Returns:
            A response object with OpenAI-style structure
        """
        # Create a simple response object that mimics OpenAI's structure using dataclasses
        @dataclass
        class Choice:
            """Choice class for OpenAI-style response"""
            message: Any

        @dataclass
        class Message:
            """Message class for OpenAI-style response"""
            content: Optional[List[Any]] = None
            tool_calls: Optional[List[Any]] = None
            thought: Optional[List[bool]] = None
            thought_signature: Optional[List[Any]] = None

        @dataclass
        class Response:
            """Response class for OpenAI-style response"""
            choices: List[Choice]
            model: str
            usage: Dict[str, int]

        # Extract content and tool calls from Gemini's response
        openai_tool_calls = []
        text_content = []
        thought_signature = []
        thought = []

        # Check if response has candidates
        if hasattr(gemini_response, 'candidates') and gemini_response.candidates:
            candidate = gemini_response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content:
                content = candidate.content
                if hasattr(content, 'parts') and content.parts:
                    for part in content.parts:
                        if hasattr(part, 'text') and part.text:
                            if hasattr(part, "thought") and part.thought is not None:
                                thought.append(True)
                            else:
                                thought.append(False)
                            if hasattr(part, "thought_signature") and part.thought_signature:
                                thought_signature.append(
                                    base64.b64encode(part.thought_signature).decode(
                                        "ascii"
                                    )
                                )
                            else:
                                thought_signature.append(None)
                            text_content.append(part.text)
                        elif hasattr(part, 'function_call') and part.function_call:
                            # Convert Gemini function call to OpenAI format
                            func_call = part.function_call
                            tool_id = str(uuid.uuid4())

                            # Create OpenAI-style tool call as dict (JSON serializable)
                            tool_call = {
                                "id": tool_id,
                                "type": "function",
                                "function": {
                                    "name": func_call.name,
                                    "arguments": (
                                        json.dumps(dict(func_call.args))
                                        if func_call.args else "{}"
                                    )
                                },
                            }
                            # Keep the thought_signature for multi-turn reasoning
                            if hasattr(part, "thought_signature") and part.thought_signature:
                                tool_call["thought_signature"] = base64.b64encode(
                                    part.thought_signature
                                ).decode("ascii")
                            openai_tool_calls.append(tool_call)

        # Set content and tool_calls
        content = text_content if text_content else None
        tool_calls = openai_tool_calls if openai_tool_calls else None

        # Create the response structure
        message = Message(
            content=content,
            thought=thought,
            tool_calls=tool_calls,
            thought_signature=thought_signature,
        )
        choice = Choice(message)
        usage = {
            "input_tokens": gemini_response.usage_metadata.prompt_token_count,
            "output_tokens": (
                gemini_response.usage_metadata.total_token_count
                - gemini_response.usage_metadata.prompt_token_count
            ),
        }
        response = Response(choices=[choice], model=self.config.model_name, usage=usage)
        return response

    def _create_gemini_content_parts(self, message: Any) -> List[Part]:
        """
        Create a Gemini content part from text, thought, and thought_signature.
        """
        text_content = message["content"]
        thought = message["thought"]
        thought_signature = message["thought_signature"]
        all_parts = []
        for j_idx, text in enumerate(text_content):
            if thought[j_idx]:
                all_parts.append(Part(text=text, thought=True))
            elif thought_signature[j_idx] is not None:
                decoded_sig = base64.b64decode(
                    thought_signature[j_idx].encode("ascii")
                )
                all_parts.append(Part(text=text, thought_signature=decoded_sig))
            else:
                all_parts.append(Part(text=text))
        return all_parts

    def _create_gemini_style_messages(self, openai_messages: List[dict]) -> List[dict]:
        """
        Create Gemini-style messages from OpenAI-style messages.
        """
        gemini_messages = []
        system_message = ""
        i = 0
        while i < len(openai_messages):
            message = openai_messages[i]
            if message["role"] == "system":
                system_message += message["content"]
                i += 1
            elif message["role"] == "user":
                gemini_messages.append(Content(
                    role="user",
                    parts=[
                        Part(text=message["content"]),
                    ],
                ))
                i += 1
            elif message["role"] == "assistant":
                if not message.get("tool_calls"):
                    parts = self._create_gemini_content_parts(message)
                    gemini_messages.append(Content(role="model", parts=parts))
                else:
                    all_parts = []
                    if message.get("content"):
                        all_parts.extend(self._create_gemini_content_parts(message))
                    if message.get("tool_calls"):
                        tool_calls = message.get("tool_calls")
                        for tool_call in tool_calls:
                            function_call_part = FunctionCall(
                                    name=tool_call["function"]["name"],
                                    args=json.loads(tool_call["function"]["arguments"]),
                            )
                            if tool_call.get("thought_signature"):
                                ts_decoded = base64.b64decode(
                                    tool_call["thought_signature"].encode(
                                        "ascii"
                                    )
                                )
                                all_parts.append(
                                    Part(
                                        function_call=function_call_part,
                                        thought_signature=ts_decoded,
                                    )
                                )
                            else:
                                all_parts.append(Part(function_call=function_call_part))
                    gemini_messages.append(Content(role="model", parts=all_parts))
                i += 1
            elif message["role"] == "tool":
                # Collect all consecutive tool messages into the same Content object
                tool_parts = []
                while i < len(openai_messages) and openai_messages[i]["role"] == "tool":
                    tool_message = openai_messages[i]
                    try:
                        tool_result = json.loads(tool_message["content"])
                    except (ValueError, json.JSONDecodeError):
                        tool_result = {"result": tool_message["content"]}
                    tool_parts.append(Part.from_function_response(
                        name=tool_message["tool_name"],
                        response=tool_result
                    ))
                    i += 1
                gemini_messages.append(Content(role="tool", parts=tool_parts))
        return system_message, gemini_messages

    def support_tool_call(self) -> bool:
        """
        Return a flag indicating if the model supports function/tool call API.
        """
        return True

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        super().set_context(context)
        self.config.api_key = context.env.get("GEMINI_API_KEY", self.config.api_key)
