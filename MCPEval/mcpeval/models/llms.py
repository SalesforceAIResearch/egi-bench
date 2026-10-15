import os
import re


# OpenAI reasoning families. Mirrors ``egi_bench/reasoning_models.py`` (the
# canonical EGI-Bench source) but kept inline here so MCPEval stays
# self-contained inside its own venv without depending on a sys.path hack
# back to the repo root. Update both files together when adding a family.
# Maintainer runbook: ``docs/reasoning-models.md`` at the repo root.
_OPENAI_REASONING_PATTERNS = (
    r"^o[134](?:[-_.]|$)",
    r"^o1(?:[-_.]|$)",
    r"^gpt-5(?:[-_.]|$)",
)


def _is_openai_reasoning_model(model_name) -> bool:
    if not isinstance(model_name, str) or not model_name:
        return False
    tail = model_name.lower().split("/")[-1]
    return any(re.search(p, tail) for p in _OPENAI_REASONING_PATTERNS)


class OpenAIWrapper:
    """Wrapper for OpenAI API to match BaseLLM interface."""

    def __init__(
        self, model="gpt-4o", api_key=None, base_url=None, model_config=None, **kwargs
    ):
        from openai import OpenAI

        # If model_config is provided, use it for configuration
        if model_config is not None:
            # Extract client-specific parameters
            client_api_key = (
                model_config.get("api_key") or api_key or os.getenv("OPENAI_API_KEY")
            )
            client_base_url = model_config.get("base_url") or base_url

            # Use model from config if provided
            self.model = model_config.get("model", model)

            # Store only the chat completion parameters from config
            self.chat_params = {
                k: v
                for k, v in model_config.items()
                if k not in ["api_key", "base_url", "model"]
            }
        else:
            # Fallback to individual parameters
            client_api_key = api_key or os.getenv("OPENAI_API_KEY")
            client_base_url = base_url
            self.model = model
            self.chat_params = {}

        # Filter out None values from kwargs to avoid passing them to OpenAI client
        client_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        if client_base_url is not None:
            client_kwargs["base_url"] = client_base_url

        # For internal endpoints, we may need to handle SSL verification
        import httpx
        import urllib3
        
        # Check if this is an internal Salesforce endpoint
        if client_base_url and "sfproxy" in client_base_url:
            # Disable SSL warnings for internal endpoints
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            # Create custom HTTP client with SSL verification disabled
            client_kwargs["http_client"] = httpx.Client(verify=False)
        
        self.client = OpenAI(api_key=client_api_key, **client_kwargs)

    def chat_completion(self, messages, tools=None, **kwargs):
        """Create a chat completion with OpenAI API."""
        # Merge stored chat parameters with any kwargs passed to this method
        # kwargs take precedence over stored config
        chat_kwargs = {**self.chat_params, **kwargs}

        # OpenAI reasoning models (o1 / o3 / o4 / gpt-5*) reject the legacy
        # ``max_tokens`` parameter and require ``max_completion_tokens``.
        # Normalize the kwarg name for any of those families so callers can
        # keep emitting ``max_tokens`` agnostically. The detection mirrors
        # ``egi_bench/reasoning_models.py`` (the canonical source); see the
        # patterns at the top of this file.
        if "max_tokens" in chat_kwargs and _is_openai_reasoning_model(self.model):
            chat_kwargs["max_completion_tokens"] = chat_kwargs.pop("max_tokens")

        response = self.client.chat.completions.create(
            model=self.model, messages=messages, tools=tools, **chat_kwargs
        )

        # Convert to dict format expected by evaluator
        return {
            "choices": [
                {
                    "message": {
                        "role": response.choices[0].message.role,
                        "content": response.choices[0].message.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": tc.type,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in (response.choices[0].message.tool_calls or [])
                        ],
                    }
                }
            ]
        }
