# LiteLLM Proxy

A local OpenAI-compatible proxy that lets every EGI-Bench benchmark
route its LLM calls through a single endpoint while supporting any
provider that [LiteLLM](https://docs.litellm.ai/) understands —
**OpenAI**, **Anthropic**, **Google Gemini**, **AWS Bedrock**, **Vertex
AI**, **OpenRouter**, **Azure OpenAI**, and self-hosted servers (vLLM,
Ollama, TGI, ...).

The benchmarks themselves never know what provider they're hitting:
they speak the standard OpenAI wire protocol against
`http://localhost:8008/v1`, and this proxy maps the requested
`model_name` to the right upstream via [`litellm_config.yaml`](litellm_config.yaml).

## Files

| File | Description |
|---|---|
| `litellm_config.yaml` | Model routing table. The only file users normally edit. |
| `start_server.sh` | Convenience startup script. Loads the repo-root `.env`. |
| `requirements.txt` | Python dependencies (`litellm[proxy]`). |

## Setup

**1. Set provider credentials in the repo-root `.env`:**

```bash
# Required for OpenAI routes and the judge / simulator pins.
OPENAI_API_KEY=sk-...

# Optional — only needed for the providers you actually use.
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
VERTEX_PROJECT=               # for vertex/ routes
VERTEX_LOCATION=us-central1
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
# AWS_ACCESS_KEY_ID=          # for bedrock/ routes
# AWS_SECRET_ACCESS_KEY=
# AWS_REGION=us-east-1
```

The proxy reads from `../.env` automatically. Shell exports take
precedence over `.env`.

**2. Install dependencies:**

```bash
cd litellm_proxy
uv venv
uv pip install -r requirements.txt
```

## Starting the Proxy

```bash
bash start_server.sh
```

The proxy listens at `http://localhost:8008` and exposes the standard
OpenAI surface plus a few LiteLLM extras:

| Endpoint | Description |
|---|---|
| `GET  /v1/models` | List configured `model_name`s |
| `POST /v1/chat/completions` | Forward chat completion requests (streaming supported) |
| `POST /v1/embeddings` | Forward embedding requests |
| `GET  /health/liveliness` | Lightweight health check (used by `egi-bench doctor`) |
| `GET  /health/readiness` | Readiness probe |

**Verify it's running:**

```bash
curl http://localhost:8008/health/liveliness
# {"status":"healthy"}

curl http://localhost:8008/v1/models | jq '[.data[].id]'
# ["gpt-5-nano", "gpt-5", "bedrock/claude-4-5-sonnet", "claude-sonnet-4-5", ...]
```

## Configuration

All routing is declared in [`litellm_config.yaml`](litellm_config.yaml).
The file is split into three sections so the structure is obvious at a
glance:

1. **Tested-model routes** — what `egi-bench run --model X` resolves to.
2. **Judge / simulator pins** — `gpt-4`, `gpt-4-turbo`, `gpt-4o`, `gpt-4.1`
   and friends are pinned to OpenAI direct regardless of which model is
   under test, so HERB's `gpt4-correctness` judge, MCP-Universe's
   sub-evaluators, and UserBench's TravelGym simulator stay on a fixed
   stack across runs (apple-to-apple scoring).
3. **Embeddings** — for HERB / PersonaBench retrieval pipelines.

To add a provider, drop a new entry into `model_list:`. See
[`docs/llm-providers.md`](../docs/llm-providers.md) for the recipe and
per-provider gotchas.

### Provider examples

**OpenAI direct:**

```yaml
- model_name: gpt-5
  litellm_params:
    model: openai/gpt-5
    api_key: os.environ/OPENAI_API_KEY
```

**Anthropic direct:**

```yaml
- model_name: claude-sonnet-4-5
  litellm_params:
    model: anthropic/claude-sonnet-4-5-20250929
    api_key: os.environ/ANTHROPIC_API_KEY
```

**Gemini direct:**

```yaml
- model_name: gemini-2.5-pro
  litellm_params:
    model: gemini/gemini-2.5-pro
    api_key: os.environ/GEMINI_API_KEY
```

**Vertex AI** (Gemini through Google Cloud; uses ADC or service-account JSON):

```yaml
- model_name: vertex/gemini-2.5-pro
  litellm_params:
    model: vertex_ai/gemini-2.5-pro
    vertex_project: os.environ/VERTEX_PROJECT
    vertex_location: os.environ/VERTEX_LOCATION
```

**AWS Bedrock** (LiteLLM handles SigV4 + per-provider message format):

```yaml
- model_name: bedrock/claude-4-5-sonnet
  litellm_params:
    model: bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0
    aws_access_key_id: os.environ/AWS_ACCESS_KEY_ID
    aws_secret_access_key: os.environ/AWS_SECRET_ACCESS_KEY
    aws_region_name: os.environ/AWS_REGION
```

**Self-hosted (vLLM, Ollama, TGI):**

```yaml
- model_name: local-llama
  litellm_params:
    model: openai/llama-3.1-70b-instruct
    api_base: http://localhost:11434/v1   # Ollama example
    api_key: any-non-empty-string
```

## Reasoning-family parameter handling

`gpt-5*`, `o1*`, `o3*`, and `o4*` reject the legacy `temperature`,
`top_p`, and `max_tokens` parameters. LiteLLM handles this automatically
as long as `litellm_settings.drop_params: true` is set (it is, by
default, in the shipped config).

If you need a hard floor on `max_completion_tokens` for a specific
reasoning model, set it per route:

```yaml
- model_name: gpt-5-nano
  litellm_params:
    model: openai/gpt-5-nano
    api_key: os.environ/OPENAI_API_KEY
    max_completion_tokens: 4096
```

## Usage from a benchmark

No benchmark code changes are needed — every adapter already speaks
OpenAI to `OPENAI_BASE_URL=http://localhost:8008/v1`. As an illustration:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8008/v1",
    api_key="dummy",   # the proxy authenticates upstream itself
)

response = client.chat.completions.create(
    model="claude-sonnet-4-5",       # any model_name from litellm_config.yaml
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

## Troubleshooting

- **`curl /health/liveliness` returns 200 but completions 401.** The
  `model_name` is configured but its upstream credential (e.g.
  `OPENAI_API_KEY`) is missing or invalid. Check `.env` and restart.
- **`Model not found` on a `model_name` you just added.** The proxy
  caches `litellm_config.yaml` at startup. Restart `start_server.sh`.
- **Reasoning model returns empty completion.** The model spent the
  budget on internal reasoning. Bump `max_completion_tokens` per route.
