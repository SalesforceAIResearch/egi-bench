import os
from litellm import completion
import litellm
litellm.set_verbose = False
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_random_exponential
from typing import Dict, List
import time, traceback
from crm_sandbox.agents.prompts import SCHEMA_STRING, REACT_RULE_STRING, SYSTEM_METADATA, REACT_EXTERNAL_INTERACTIVE_PROMPT, REACT_INTERNAL_INTERACTIVE_PROMPT, REACT_INTERNAL_PROMPT, REACT_EXTERNAL_PROMPT, REACT_PRIVACY_AWARE_EXTERNAL_PROMPT, REACT_PRIVACY_AWARE_EXTERNAL_INTERACTIVE_PROMPT, ACT_PROMPT
from crm_sandbox.agents.utils import (
    parse_wrapped_response,
    BEDROCK_MODELS_MAP,
    TOGETHER_MODELS_MAP,
    VERTEX_MODELS_MAP,
    is_openai_reasoning_model,
    is_gemini_reasoning_model,
    is_long_context_reasoning_model,
)
import together


# Token budgets. Reasoning models (OpenAI o1/gpt-5, Gemini 2.5+ thinking,
# deepseek-r1, ...) burn most of the output budget on hidden reasoning, so
# they need a much higher cap than non-reasoning models. See
# crm_sandbox/agents/utils.py for the detection rules.
_DEFAULT_MAX_TOKENS = 2000
_REASONING_MAX_TOKENS = 50000


def _max_tokens_for(model_name: str) -> int:
    return _REASONING_MAX_TOKENS if is_long_context_reasoning_model(model_name) else _DEFAULT_MAX_TOKENS


@retry(wait=wait_random_exponential(multiplier=1, max=40), stop=stop_after_attempt(10))
def chat_completion_request_openai_compat(messages, model, base_url, max_tokens=_DEFAULT_MAX_TOKENS):
    """
    Send a chat completion via any OpenAI-compatible endpoint (e.g. the local
    LiteLLM proxy).  Uses the openai SDK directly.
    """
    client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY", "dummy"),
        base_url=base_url,
    )
    return client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )





class ChatAgent:
    def __init__(
        self, schema_obj, model: str = "gpt-4o", max_turns: int = 20, eval_mode="default", strategy="react", provider="bedrock", interactive=False, agent_type="internal", privacy_aware_prompt=False, base_url: str = None
    ):
        schema = self._build_schema(schema_obj)
        assert strategy in ["react", "act"], "Only react and act strategies supported for now"
        assert agent_type in ["internal", "external"], "Invalid agent type"
        
        if strategy == "react":
            # react strategy
            if not interactive:
                if agent_type == "internal":
                    self.sys_prompt = REACT_INTERNAL_PROMPT.format(system_description=schema, system="Salesforce instance") # add strategy template and schema description
                else:
                    if privacy_aware_prompt:
                        self.sys_prompt = REACT_PRIVACY_AWARE_EXTERNAL_PROMPT.format(system_description=schema, system="Salesforce instance") # add strategy template and schema description
                    else:
                        self.sys_prompt = REACT_EXTERNAL_PROMPT.format(system_description=schema, system="Salesforce instance") # add strategy template and schema description
            else:
                if agent_type == "internal":
                    self.sys_prompt = REACT_INTERNAL_INTERACTIVE_PROMPT.format(system_description=schema, system="Salesforce instance") # add strategy template and schema description
                else:
                    if privacy_aware_prompt:
                        self.sys_prompt = REACT_PRIVACY_AWARE_EXTERNAL_INTERACTIVE_PROMPT.format(system_description=schema, system="Salesforce instance") # add strategy template and schema description
                    else:
                        self.sys_prompt = REACT_EXTERNAL_INTERACTIVE_PROMPT.format(system_description=schema, system="Salesforce instance") # add strategy template and schema description
        else:
            # act strategy
            self.sys_prompt = ACT_PROMPT.format(system_description=schema, system="Salesforce instance")
        
        self.agent_type = agent_type
        self.original_model_name = model
        self.model = model
        self.eval_mode = eval_mode
        self.max_turns = max_turns
        self.strategy = strategy
        self.info = {}
        self.usage = {"cost": [], "completion_tokens": [], "prompt_tokens": [], "total_tokens": []}
        self.provider = provider
        self.base_url = base_url

        if base_url is not None:
            pass  # model name used as-is against the custom endpoint
        elif provider == "bedrock" and self.model in BEDROCK_MODELS_MAP:
            os.environ["AWS_REGION_NAME"] = BEDROCK_MODELS_MAP[self.model]["region"]
            self.model = BEDROCK_MODELS_MAP[self.model]["name"]
        elif provider == "together_ai" and self.model in TOGETHER_MODELS_MAP:
            self.model = TOGETHER_MODELS_MAP[self.model]["name"]
        elif "vertex" in provider and self.model in VERTEX_MODELS_MAP:
            self.model = VERTEX_MODELS_MAP[self.model]["name"]
            
        else:
            pass
        if self.model in ["o1-mini", "o1-preview", "o1-2024-12-17", "o3-mini-2025-01-31"]:
            import litellm
            
            litellm.drop_params=True
            print("dropping parameters")
            
            # assert self.model in ["o1-mini", "o1-preview", "gpt-4o-2024-08-06", "gpt-3.5-turbo-0125"], "Invalid model name"
    
    def _build_schema(self, schema_obj):
        object_description = dict()
        for item in schema_obj:
            object_description[item["object"]] = "\n".join([f"  - {k}: {v}" for k,v in item["fields"].items()])
            
        template = SCHEMA_STRING.format(
            object_names=", ".join(object_description.keys()),
            object_fields="\n".join(
                [f"{obj}\n{fields}" for obj, fields in object_description.items()]
            )
        )
        return template
    
    def reset(self, args):
        if args["metadata"]["required"]:
            self.sys_prompt += SYSTEM_METADATA.format(system_metadata=args["metadata"]["required"], system="Salesforce instance") # add task/query-specific metadata here
        if self.eval_mode == "aided" and "optional" in args["metadata"]:
            self.sys_prompt += "\n" + args["metadata"]["optional"]
        # Some upstream APIs reject the ``system`` role and want the system
        # prompt folded into the first user message instead. Today this is
        # only the OpenAI o1 family and deepseek-r1; modern Gemini 2.5+
        # endpoints (both direct and via the litellm proxy) accept the
        # standard system+user shape, so we keep them on the default path.
        _no_system_role = (
            self.original_model_name in {
                "o1-mini",
                "o1-preview",
                "o1-2024-12-17",
                "deepseek-r1",
                "o3-mini-2025-01-31",
                "gemini-2.5-flash-preview-04-17",
            }
        )
        if not _no_system_role:
            self.messages = [{"role": "system", "content": self.sys_prompt.strip()}]
            self.messages.append({"role": "user", "content": args["query"].strip()})
        else:
            self.messages = [{"role": "user", "content": self.sys_prompt + "\n\n" + args["query"]}]
        self.usage = {"cost": [], "completion_tokens": [], "prompt_tokens": [], "total_tokens": []}
        
    def act(self, env, index=None, temperature=0.0):
        query, metadata = env.reset(task_index=index)
        self.reset({"query": query, "metadata": metadata})
        # print("----")
        # print(self.sys_prompt)
        # print("----")
        total_cost = 0.0
        self.info["observation_sizes"] = []
        done = False
        reward = 0
        
        current_agent_turn = 0
        # for turn_id in range(self.max_turns):
        while current_agent_turn < self.max_turns:
            # sleep for non-openai models
            if self.provider != "openai":
                time.sleep(5)
            info = {}
            current_agent_turn += 1
            # Gemini 2.5 thinking-budget overrides for the dated previews
            # (only the litellm-direct path supports the ``thinking`` knob;
            # the openai-compat / proxy path relies on the upstream's default
            # thinking config and just leaves headroom via ``max_tokens``).
            if self.original_model_name == "gemini-2.5-flash-preview-04-17":
                thinking = {"type": "disabled", "budget_tokens": 0}
            elif self.original_model_name == "gemini-2.5-flash-preview-04-17-thinking-4096":
                thinking = {"type": "enabled", "budget_tokens": 4096}
            else:
                thinking = None

            # Reasoning models (OpenAI o1/gpt-5, Gemini 2.5+ thinking
            # variants like ``vertex/gemini-2.5-flash``, deepseek-r1, ...)
            # need a 50k completion budget; everything else gets the default
            # 2k. See crm_sandbox/agents/utils.py for the detection rules.
            max_tokens = _max_tokens_for(self.original_model_name)

            if self.base_url is not None:
                res = chat_completion_request_openai_compat(
                    messages=self.messages,
                    model=self.model,
                    base_url=self.base_url,
                    max_tokens=max_tokens,
                )
                usage_dict = res.usage.model_dump() if res.usage else {}
                for key in self.usage.keys():
                    if key != "cost":
                        self.usage[key].append(usage_dict.get(key, 0) or 0)
                self.usage["cost"].append(0)
            else:
                # OpenAI o1/o3/gpt-5 reject ``temperature`` (and o3-mini also
                # rejects ``top_p``); drop them at the litellm layer rather
                # than maintaining hand-rolled allowlists.
                drop_params = (
                    ["temperature"]
                    if is_openai_reasoning_model(self.original_model_name)
                    or self.original_model_name == "deepseek-r1"
                    else []
                )
                res = completion(
                    messages=self.messages,
                    model=self.model,
                    temperature=0.0,
                    max_tokens=max_tokens,
                    top_p=1.0 if self.model not in ["o3-mini-2025-01-31"] else None,
                    thinking=thinking,
                    additional_drop_params=drop_params,
                )
                usage = res.usage
                for key in self.usage.keys():
                    if key != "cost":
                        self.usage[key].append(usage.get(key, 0))
                self.usage["cost"].append(res._hidden_params["response_cost"])

            message = res.choices[0].message.model_dump()
            action = self.message_action_parser(message, self.model)
            print("User Turn:", env.current_user_turn, "Agent Turn:", current_agent_turn, "Agent:", message["content"].strip())
            self.messages.append({"role": "assistant", "content": message["content"].strip()})
            if action is None:
                self.info["end_reason"] = {
                    "source": "agent",
                    "message": "Invalid action",
                    "content":  message["content"].strip()
                }
                info["end_reason"] = self.info["end_reason"]
                if self.strategy == "react":
                    self.messages.append({"role": "user", "content": REACT_RULE_STRING})
                elif self.strategy == "act":
                    self.messages.append({"role": "user", "content": ACT_RULE_STRING})
                continue
            obs, reward, done, info = env.step(action)
            
            if "observation_size" in info:
                self.info["observation_sizes"].append(info["observation_size"])
            if "end_reason" in info: # implies error in query
                self.info["end_reason"] = info["end_reason"]
            # reset counter if previous action is respond
            if action["name"] == "respond":
                current_agent_turn = 0
            if done:
                break
            elif action["name"] == "execute": # execution results from
                self.messages.append({"role": "user", "content": f"Salesforce instance output: {obs}"})
            elif action["name"] == "respond": # respond to simulated user
                self.messages.append({"role": "user", "content": obs})
        
        # Here when either max_turns is reached or submitted
        if not done: 
            if "end_reason" not in info: # no error in last query
                self.info["end_reason"] = {
                    "source": "agent",
                    "message": "Max turns reached",
                    "content":  message["content"].strip()
                }
        self.info["usage"] = self.usage
        self.info["total_cost"] = sum(cost for cost in self.usage["cost"] if cost is not None)
        self.info["num_turns"] = (env.current_user_turn, current_agent_turn + 1)
        return reward

    def get_messages(self) -> List[Dict[str, str]]:
        return self.messages

    @staticmethod
    def message_action_parser(message: str, model_name: str) -> Dict[str, str]:
        action = None
        content = message["content"].strip()
        # if model_name "deepseek-r1":
        #     content = content.split("</think>")[1]
        resp = parse_wrapped_response(r'<execute>(.*?)</execute>', content).strip()
        if resp:
            action = {"name": "execute", "content": resp}
            return action
        
        resp = parse_wrapped_response(r'<respond>(.*?)</respond>', content).strip()
        if resp:
            action = {"name": "respond", "content": resp}
            return action
        return action