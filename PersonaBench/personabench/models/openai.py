import openai
import os

class OpenAIGPT:
    def __init__(self, api_key, model) -> None:
        self.api_key = api_key
        self.model = model
        # Support both modern and legacy env vars for local OpenAI-compatible proxies.
        base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
        if base_url:
            self.client = openai.OpenAI(api_key=self.api_key, base_url=base_url)
        else:
            self.client = openai.OpenAI(api_key=self.api_key)
    
    def generate(self, prompt):
        if "system" in prompt:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt['system']},
                    {"role": "user", "content": prompt['instruction']}
                ]
            )
        else:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt['instruction']}
                ]
            )
        # Some providers (notably Vertex Gemini and reasoning models that emit a
        # tool_calls-only or refusal response) return ``content=None``. Coerce
        # to an empty string so the downstream evaluator can still record an
        # empty answer instead of crashing the whole community sweep on
        # ``AttributeError: 'NoneType' object has no attribute 'strip'``.
        content = response.choices[0].message.content or ""
        return content.strip()