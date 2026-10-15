import re
import string
from collections import Counter
from typing import Optional

from sacrebleu.metrics import BLEU
from rouge import Rouge


# Reasoning-style models (OpenAI o-series, the GPT-5 family, Gemini 2.5 / 3,
# Claude 3.7 + 4.x, DeepSeek-R1, ...) can spend their entire output budget on
# internal reasoning tokens before emitting any visible content. When that
# happens the call either returns an empty completion (which the agent loop
# then interprets as "Invalid action") or, on some gateways, surfaces as an
# HTTP 400. The benchmark adapters under this directory therefore need to
# (a) detect such models and (b) bump the per-call ``max_tokens`` budget.
# The detection rules below intentionally tolerate provider-routing prefixes
# like ``vertex/``, ``vertex_ai/``, ``gemini/``, ``express/``, ``openai/``,
# ``anthropic/``, etc. so the same helper works against the local LiteLLM
# proxy, direct provider calls, and the bedrock/vertex maps in this file.
#
# CANONICAL SOURCE: ``egi_bench/reasoning_models.py`` at the repo root holds
# the master copy of these patterns. CRMArena is its own venv (no egi_bench
# install), so we keep a self-contained mirror here. When you add a model
# family, please update both files together. The maintainer runbook
# (when to add, how to pick regex vs exact, how to test) lives at
# ``docs/reasoning-models.md``.

# OpenAI reasoning families. Use a prefix check on the gpt-5 side so future
# point releases (gpt-5.4, gpt-5.5, gpt-5.5-mini, gpt-5.4-nano, ...) auto-
# qualify without code changes.
_OPENAI_REASONING_PATTERNS = (
    r"^o[134](?:[-_.]|$)",
    r"^o1(?:[-_.]|$)",
    r"^gpt-5(?:[-_.]|$)",
)

# Gemini reasoning families. Note the literal ``.`` in ``gemini-2.5``; some
# gateways lower-case to ``gemini-2-5`` so we accept both shapes. Excludes
# Gemini 2.0 / 1.5, which are not thinking models.
_GEMINI_REASONING_PATTERNS = (
    r"gemini-2[._-]5(?:[-_.]|$)",
    r"gemini-3(?:[-_.]|$)",
)

# Anthropic reasoning families (Claude 3.7 + Claude 4.x). Extended thinking
# is opt-in for Claude (callers must pass ``thinking={"type":"enabled",...}``),
# so today CRMArena's agents -- which never set that flag -- aren't affected
# by the thinking-budget truncation bug. We still classify these as reasoning
# for two reasons: (1) MCP-Universe's claude_wr / claude_gateway / sf_research
# gateway adapters DO enable Claude thinking and need the bumped cap, and
# (2) it keeps the classification aligned with UserBench's
# ``travelgym/_token_utils.py``. Patterns match the family token regardless
# of where it falls in routed names like
# ``anthropic.claude-sonnet-4-20250929-v1:0`` or
# ``bedrock/us.anthropic.claude-3-7-sonnet-20250219-v1:0``. Order doesn't
# matter -- we ``re.search`` each pattern.
_CLAUDE_REASONING_PATTERNS = (
    r"claude-3-7(?:[-_.]|$)",
    r"claude-sonnet-4(?:[-_.]|$)",
    r"claude-opus-4(?:[-_.]|$)",
    r"claude-haiku-4(?:[-_.]|$)",
    r"claude-4(?:[-_.]|$)",
)

# Other long-context reasoning models that need the same bumped budget on the
# OpenAI-compat / litellm paths even though they don't fit the OpenAI,
# Gemini, or Claude families above (e.g. DeepSeek-R1 also burns its output
# budget on hidden reasoning).
_OTHER_REASONING_EXACT = {
    "deepseek-r1",
}


def _normalize_model_name(model_name: Optional[str]) -> str:
    if not model_name:
        return ""
    return model_name.lower()


def _matches_any(name: str, patterns) -> bool:
    return any(re.search(p, name) for p in patterns)


def is_openai_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True for OpenAI reasoning models (o1/o3/o4 + gpt-5*).

    Tolerates routing prefixes like ``openai/o1-mini`` or ``sfr/gpt-5``.
    """
    name = _normalize_model_name(model_name)
    if not name:
        return False
    tail = name.split("/")[-1]
    return _matches_any(tail, _OPENAI_REASONING_PATTERNS)


def is_gemini_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True for Gemini reasoning models (2.5 family, 3.x family).

    Matches every variant exposed by the LiteLLM proxy:
    ``gemini-2.5-flash``, ``gemini-2.5-pro``, ``vertex/gemini-2.5-*``,
    ``vertex_ai/gemini-2.5-*``, ``gemini/gemini-2.5-*``,
    ``express/gemini-2.5-*``, plus the dated previews
    (``gemini-2.5-flash-preview-04-17``, ``gemini-2.5-pro-preview-03-25``).
    Returns False for ``gemini-2.0-flash`` / ``gemini-1.5-pro``.
    """
    name = _normalize_model_name(model_name)
    if not name:
        return False
    return _matches_any(name, _GEMINI_REASONING_PATTERNS)


def is_claude_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True for Claude reasoning models (3.7 family, 4.x family).

    Matches the family token wherever it appears in the routed name, so all
    of ``claude-sonnet-4-5``, ``claude-opus-4-5``,
    ``bedrock/claude-3-7-sonnet``, ``bedrock/us.anthropic.claude-opus-4-...``,
    ``express/claude-sonnet-4-6``, etc. qualify. Returns False for Claude
    3.5 and earlier, which don't support extended thinking.
    """
    name = _normalize_model_name(model_name)
    if not name:
        return False
    return _matches_any(name, _CLAUDE_REASONING_PATTERNS)


def is_long_context_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True for any model that needs a bumped output-token budget.

    Used by ``ToolCallAgent`` / ``ChatAgent`` to pick between the default
    ``max_tokens`` cap and a much larger reasoning cap (~50000 tokens).
    """
    if (
        is_openai_reasoning_model(model_name)
        or is_gemini_reasoning_model(model_name)
        or is_claude_reasoning_model(model_name)
    ):
        return True
    name = _normalize_model_name(model_name)
    if not name:
        return False
    tail = name.split("/")[-1]
    return name in _OTHER_REASONING_EXACT or tail in _OTHER_REASONING_EXACT

## MODEL MAP ##
BEDROCK_MODELS_MAP = {
    "llama-3.1-70b-instruct": {
        "name": "meta.llama3-1-70b-instruct-v1:0",
        "region": "us-west-2",
    },
    "llama-3.1-70b-instruct": {
        "name": "meta.llama3-1-8b-instruct-v1:0",
        "region": "us-west-2",
    },
    "llama-3.1-405b-instruct": {
        "name": "meta.llama3-1-405b-instruct-v1:0",
        "region": "us-west-2",
    },
    "claude-3-5-sonnet-20240620" : {
        "name": "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "region": "us-east-1",
    },
    "claude-3-opus-20240229" : {
        "name": "anthropic.claude-3-opus-20240229-v1:0",
        "region": "us-west-2",
    },
    "claude-3-haiku-20240307" : {
        "name": "anthropic.claude-3-haiku-20240307-v1:0",
        "region": "us-west-2",
    },
    "mistral_large": {
        "name": "mistral.mistral-large-2407-v1:0",
        "region": "us-west-2",
    },
    "mixtral_8x7b_instruct": {
        "name": "mistral.mixtral-8x7b-instruct-v0:1",
        "region": "us-east-1",
    },
    "mistral_7b_instruct_v0.2" : {
        "name": "mistral.mistral-7b-instruct-v0:2",
        "region": "us-west-2",
    }
}

TOGETHER_MODELS_MAP = {
    "llama3.1-405b-instruct" : {
        "name": "together_ai/meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
    },
    "mixtral_8x22b_instruct" : {
        "name": "together_ai/mistralai/Mixtral-8x22B-Instruct-v0.1"
    },
    "llama3.1-8b-instruct" : {
        "name": "together_ai/meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"
    },
    "llama3.1-70b-instruct" : {
        "name": "together_ai/meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"
    },
    "llama4-maverick-17b-128e-instruct" : {
        "name": "together_ai/meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"
    },
    "deepseek-r1" : {
        "name": "together_ai/deepseek-ai/DeepSeek-R1"
    }
}

VERTEX_MODELS_MAP = {
  "llama3.1-405b-instruct": {
    "name": "vertex_ai/meta/llama3-405b-instruct-maas"
  },
  "llama3.1-70b-instruct" : {
        "name": "vertex_ai/meta/llama3-70b-instruct-maas"
    },
  "llama3.1-8b-instruct" : {
        "name": "vertex_ai/meta/llama3-8b-instruct-maas"
    },
  "llama4-maverick-17b-128e-instruct": {
        "name": "vertex_ai/meta/llama-4-maverick-17b-128e-instruct-maas"
  },
  "gemini-2.5-flash-preview-04-17": {
        "name": "vertex_ai/gemini-2.5-flash-preview-04-17"
  },
  "gemini-2.5-flash-preview-04-17-thinking-4096":{
        "name": "vertex_ai/gemini-2.5-flash-preview-04-17"
  },
  "gemini-2.5-pro-preview-03-25": {
        "name": "vertex_ai/gemini-2.5-pro-preview-03-25"
  },
  "gemini-2.0-flash-001":{
        "name": "vertex_ai/gemini-2.0-flash-001"
  }
}

### Utils ###
def parse_wrapped_response(reg_exp, text_phrase):
    match = re.search(reg_exp, text_phrase, re.DOTALL)
    if match:
        return match.group(1)
    return ""

def fc_prompt_builder(tools):
    """
    tools: tool_info [tool.__info__ for tool in tools]
    """
    
    output = []
    for tool in tools:
        tool_name = tool['function']['name']
        tool_description = tool['function']['description']

        tool_string = f"> Tool Name: {tool_name}\n"
        tool_string += f"Tool Description: {tool_description}\n"
        tool_string += "Tool Args:\n"

        parameters = tool['function']['parameters']['properties']
        required_params = tool['function']['parameters'].get('required', [])

        for param, details in parameters.items():
            param_type = details['type']
            required = param in required_params
            required_str = ", required" if required else ""
            description = details.get('description', '')

            if param_type == 'array':
                item_type = details.get('items', {}).get('type', '')
                # param_type += f", where each item should be {item_type}" if item_type else ""

            tool_string += f"  - {param} ({param_type}{required_str}): {description.strip()}\n"

        output.append(tool_string.strip())

    output = "You have access to the following tools:\n" + "\n\n".join(output).strip()
    output += """
    Use the following format if using a tool:
    ```
    Action: tool name (one of [get_agents_with_max_cases, get_agents_with_min_cases, calculate_average_handle_time, get_start_date, get_period, get_agent_handled_cases_by_period, get_qualified_agent_ids_by_case_count, get_cases, get_non_transferred_case_ids, get_agent_transferred_cases_by_period, get_shipping_state, calculate_region_average_closure_times, get_order_item_ids_by_product, get_issue_counts, find_id_with_max_value, find_id_with_min_value, get_account_id_by_contact_id, get_purchase_history, get_month_to_case_count, search_knowledge_articles, search_products, get_issues, submit, get_livechat_transcript_by_case_id, get_email_messages_by_case_id])
    Action Input: the input to the tool, in a JSON format representing the kwargs (e.g. ```{"input": "hello world", "num_beams": 5}```)
    ```
    """
    return output

    
### Metrics ###
bleu_scorer = BLEU()
rouge_scorer = Rouge()

def normalize_answer(s):
    """Lower text and remove punctuation, articles and extra whitespace."""

    def remove_articles(text):
        return re.sub(r'\b(a|an|the)\b', ' ', text)

    def white_space_fix(text):
        return ' '.join(text.split())

    def handle_punc(text):
        exclude = set(string.punctuation + "".join([u"‘", u"’", u"´", u"`"]))
        return ''.join(ch if ch not in exclude else ' ' for ch in text)

    def lower(text):
        return text.lower()

    def replace_underscore(text):
        return text.replace('_', ' ')

    return white_space_fix(remove_articles(handle_punc(lower(replace_underscore(s))))).strip()


def exact_match_score(prediction, ground_truth):
    return normalize_answer(prediction) == normalize_answer(ground_truth)


def f1_score(prediction, ground_truth):
    prediction_tokens = normalize_answer(prediction).split()
    ground_truth_tokens = normalize_answer(ground_truth).split()
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0
    precision = 1.0 * num_same / len(prediction_tokens)
    recall = 1.0 * num_same / len(ground_truth_tokens)
    f1 = (2 * precision * recall) / (precision + recall)
    return f1


def bleu_score(prediction, ground_truth):
    score = bleu_scorer.sentence_score(
        hypothesis=normalize_answer(prediction),
        references=[normalize_answer(ground_truth)],
    )
    return score.score / 100

def rouge_score(prediction, ground_truth):
    score = rouge_scorer.get_scores(
        hyps=normalize_answer(prediction),
        refs=normalize_answer(ground_truth),
    )
    return {
        "rouge-1": score[0]["rouge-1"]["f"],
        "rouge-2": score[0]["rouge-2"]["f"],
        "rouge-l": score[0]["rouge-l"]["f"],
    }
    
def get_all_metrics(prediction, ground_truth):
    em = exact_match_score(prediction, ground_truth)
    f1 = f1_score(prediction, ground_truth)
    bleu = bleu_score(prediction, ground_truth)
    rouge = rouge_score(prediction, ground_truth)
    return {
        "em": em,
        "f1": f1,
        "bleu": bleu,
        "rouge": rouge,
    }