import json
import os
from openai import OpenAI

def get_gpt4_response(messages, model_name="gpt-4o", temperature=0.00001, response_format="text"):
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
    api_key = os.environ.get("OPENAI_API_KEY") or "dummy"
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    generation_params = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        **({"response_format": {"type": "json_object"}} if response_format == "json" else {}),
    }
    chat_completions = client.chat.completions.create(**generation_params)
    response = chat_completions.choices[0].message.content
    if response_format == "json":
        try:
            parsed = json.loads(response)
            # Gemini sometimes wraps the JSON object in a one-element array;
            # unwrap so downstream callers that expect a dict keep working.
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed[0]
            return parsed
        except Exception:
            return None
    return response.strip()