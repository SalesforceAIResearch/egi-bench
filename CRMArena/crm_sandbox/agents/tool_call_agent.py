import copy
import json, os
from litellm import completion, completion_cost
from typing import Dict, List, Any
import re, traceback, ast, time
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_random_exponential
from crm_sandbox.agents.prompts import SCHEMA_STRING, SYSTEM_METADATA, NATIVE_FC_PROMPT, CUSTOM_FC_PROMPT, FC_RULE_STRING, FC_FLEX_PROMPT
from crm_sandbox.agents.utils import (
    parse_wrapped_response,
    BEDROCK_MODELS_MAP,
    TOGETHER_MODELS_MAP,
    VERTEX_MODELS_MAP,
    fc_prompt_builder,
    is_openai_reasoning_model,
    is_gemini_reasoning_model,
    is_long_context_reasoning_model,
)


# Reasoning-model detection: see crm_sandbox/agents/utils.py for the rules.
# OpenAI reasoning models (o1/o3/o4/gpt-5*) reject ``temperature`` / ``top_p``
# and want ``max_completion_tokens`` instead of ``max_tokens``. Gemini 2.5+
# (Flash/Pro, including provider-prefixed variants like
# ``vertex/gemini-2.5-flash``) is a "thinking" model that burns its output
# budget on internal reasoning -- without a bumped cap the visible content
# truncates to literally ``"None"`` with no tool_calls (see
# results_aggregated/logs/crmarena_quick_*.log for the failure shape).
def _is_o1_or_gpt5_family(model: str) -> bool:
    """Backwards-compatible alias for OpenAI o1/gpt-5 detection."""
    return is_openai_reasoning_model(model)


def _is_long_context_reasoning_model(model: str) -> bool:
    """True for any model that needs the bumped completion-token budget.

    Includes OpenAI reasoning, Gemini 2.5/3 thinking models (regardless of
    ``vertex/``, ``vertex_ai/``, ``gemini/``, ``express/`` prefix), and a
    handful of other long-context reasoners (deepseek-r1, ...).
    """
    return is_long_context_reasoning_model(model)


# Token budget for reasoning models. Empirically Gemini 2.5 Flash thinks for
# 5-15k tokens before emitting visible content on CRMArena tool-call traces;
# 50000 leaves comfortable headroom for the actual tool call / response.
_REASONING_MAX_TOKENS = 50000
_DEFAULT_MAX_TOKENS = 3500


@retry(wait=wait_random_exponential(multiplier=1, max=40), stop=stop_after_attempt(10))
def chat_completion_request(
    messages,
    model,
    tools=None,
    temperature: float = 0.0,
    top_p=1.0,
    max_tokens=_DEFAULT_MAX_TOKENS,
    additional_drop_params=[]
):
    res = completion(
        messages=messages,
        model=model,
        temperature=0.0,
        top_p=1.0,
        max_tokens=_REASONING_MAX_TOKENS if _is_long_context_reasoning_model(model) else _DEFAULT_MAX_TOKENS,
        tools=tools if "llama" not in model else None, ## llama tool_calling through prompt
        additional_drop_params=["temperature", "top_p"] if _is_o1_or_gpt5_family(model) else []
    )
    return res


@retry(wait=wait_random_exponential(multiplier=1, max=40), stop=stop_after_attempt(10))
def chat_completion_request_openai_compat(messages, model, base_url, tools=None):
    """
    Send a chat completion via any OpenAI-compatible endpoint (e.g. the local
    LLM Gateway proxy).  Uses the openai SDK so tool-calling works out of the box.
    """
    client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY", "dummy"),
        base_url=base_url,
    )
    kwargs = {"model": model, "messages": messages}

    if _is_o1_or_gpt5_family(model):
        # OpenAI reasoning models (o1, gpt-5 family incl. gpt-5.4 / gpt-5.5
        # / ...) need ``max_completion_tokens`` and reject temperature/top_p.
        kwargs["max_completion_tokens"] = _REASONING_MAX_TOKENS
    elif _is_long_context_reasoning_model(model):
        # Other long-context reasoning models (Gemini 2.5/3 thinking,
        # deepseek-r1, ...). They accept temperature/top_p and the standard
        # ``max_tokens`` parameter, but burn most of the budget on internal
        # reasoning -- so we keep the deterministic sampling settings while
        # also bumping the cap high enough for the tool call / response to
        # fit alongside the hidden thoughts.
        kwargs["temperature"] = 0.0
        kwargs["top_p"] = 1.0
        kwargs["max_tokens"] = _REASONING_MAX_TOKENS
    else:
        kwargs["temperature"] = 0.0
        kwargs["top_p"] = 1.0
        kwargs["max_tokens"] = _DEFAULT_MAX_TOKENS

    if tools:
        kwargs["tools"] = _sanitize_openai_tools(tools)
    return client.chat.completions.create(**kwargs)


def _sanitize_openai_tools(tools):
    """Normalize tool schemas for strict OpenAI-compatible backends (e.g. Gemini adapters)."""
    sanitized = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        tool_copy = copy.deepcopy(tool)
        fn = tool_copy.get("function", {})
        params = fn.get("parameters")
        if isinstance(params, dict):
            props = params.get("properties")
            required = params.get("required")
            if isinstance(props, dict) and isinstance(required, list):
                filtered_required = [k for k in required if k in props]
                if filtered_required:
                    params["required"] = filtered_required
                else:
                    params.pop("required", None)
            if not params.get("type"):
                params["type"] = "object"
            fn["parameters"] = params
            tool_copy["function"] = fn
        sanitized.append(tool_copy)
    return sanitized


class ToolCallAgent:
    def __init__(
        self, tools, schema_obj, model: str = "gpt-4o", max_turns: int = 20, eval_mode="default", strategy="tool_call", provider="bedrock", base_url: str = None
    ):
        schema = self._build_schema(schema_obj)
        self.tools = tools
        
        if strategy == "tool_call":
            if "llama" in model: # llama tool_calling through prompt
                self.sys_prompt = CUSTOM_FC_PROMPT.format(native_fc_prompt=NATIVE_FC_PROMPT.format(system="Salesforce instance"), tools_prompt=fc_prompt_builder(tools))
            else:
                self.sys_prompt = NATIVE_FC_PROMPT.format(system="Salesforce instance")
        else:
            self.sys_prompt = FC_FLEX_PROMPT.format(system_description=schema, system="Salesforce instance")
            
        self.model = model
        self.eval_mode = eval_mode
        self.max_turns = max_turns
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
            assert (
                self.model in [
                    "o1-mini", "o1-2024-12-17", "o1-preview",
                    "gpt-4o", "gpt-4o-mini", "gpt-4o-2024-08-06", "gpt-4o-2024-11-20",
                    "gpt-3.5-turbo-0125",
                ]
                or _is_o1_or_gpt5_family(self.model)
            ), f"Invalid model name: {self.model}"
            

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
        if self.model not in ["o1-mini", "o1-2024-12-17", "o1-preview", "gpt-5", "gpt-5-mini"]:
            self.messages = [{"role": "system", "content": self.sys_prompt.strip()}]
            self.messages.append({"role": "user", "content": args["query"].strip()})
        else:
            # No system role for o1/gpt-5 reasoning models
            self.messages = [{"role": "user", "content": self.sys_prompt + "\n\n" + args["query"]}]
        self.usage = {"cost": [], "completion_tokens": [], "prompt_tokens": [], "total_tokens": []}
        
    def act(self, env, index=None, temperature=0.0):
        query, metadata = env.reset(task_index=index)
        self.reset({"query": query, "metadata": metadata})
        self.info = {}
        self.info["observation_sizes"] = []
        done = False
        reward = 0
        
        for turn_id in range(self.max_turns):
            time.sleep(3)
            info = {}
            if self.base_url is not None:
                res = chat_completion_request_openai_compat(
                    messages=self.messages,
                    model=self.model,
                    base_url=self.base_url,
                    tools=self.tools if "llama" not in self.model else None,
                )
                usage_dict = res.usage.model_dump() if res.usage else {}
                for key in self.usage.keys():
                    if key != "cost":
                        self.usage[key].append(usage_dict.get(key, 0) or 0)
                self.usage["cost"].append(0)
            else:
                res = chat_completion_request(
                    messages=self.messages,
                    model=self.model,
                    temperature=0.0,
                    top_p=1.0,
                    max_tokens=3500,
                    tools=self.tools if "llama" not in self.model else None,
                    additional_drop_params=["temperature"] if _is_o1_or_gpt5_family(self.model) else []
                )
                usage = res.usage
                for key in self.usage.keys():
                    if key != "cost":
                        self.usage[key].append(usage.get(key, 0))
                self.usage["cost"].append(res._hidden_params["response_cost"])
            message = res.choices[0].message.model_dump()
            
            print("message", message, flush=True)
            action = self.message_action_parser(message)
            print("#", turn_id, "Agent action:", action, flush=True)
            
            
            if action is None:
                message_content = message.get("content")
                if not isinstance(message_content, str):
                    message_content = ""
                self.info["end_reason"] = {
                    "source": "agent",
                    "message": "Invalid action",
                    "content": message_content.strip()
                }
                info["end_reason"] = self.info["end_reason"]
                # if tool_call attempted but failed
                if "llama" not in self.model and "tool_calls" in message and message["tool_calls"] is not None and len(message["tool_calls"]) > 0 and "id" in message["tool_calls"][0]:
                    message["tool_calls"] = message["tool_calls"][:1]
                    self.messages.append(message)
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": message["tool_calls"][0]["id"].strip(),
                            "name": message["tool_calls"][0]["function"]["name"].strip(),
                            "content": f"Invalid tool call argument. Please make a valid tool call using the tools provided or submit the final answer using the 'respond' tool."
                        }
                    )
                # if no valid tool_call or not llama
                else:
                    if "llama" in self.model:
                        message_content = message.get("content")
                        if not isinstance(message_content, str):
                            message_content = ""
                        self.messages.append({"role": "assistant",
                                              "content": message_content.strip()
                                            })
                    else:
                        self.messages.append(message)
                    self.messages.append({"role": "user", "content": FC_RULE_STRING})
                continue
            else:
                if "llama" in self.model:
                    message = {
                        "role": "assistant",
                        "content": f"Action: {action['name']}\nAction Input: {json.dumps(action['arguments'])}"
                    }
                    self.messages.append(message)
                else:
                    if message.get("tool_calls"):
                        message["tool_calls"] = message["tool_calls"][:1]
                    else:
                        # Gemini gateway fallback: action came from plain-text
                        # parsing (see message_action_parser); synthesize a
                        # tool_call so the assistant + tool message pair is
                        # still well-formed for downstream gateways.
                        synthetic_id = f"call_synth_{int(time.time() * 1000)}"
                        message["tool_calls"] = [
                            {
                                "id": synthetic_id,
                                "type": "function",
                                "function": {
                                    "name": action["name"],
                                    "arguments": json.dumps(action["arguments"]),
                                },
                            }
                        ]
                    self.messages.append(message)
            
            obs, reward, done, info = env.step(action)
            if "observation_size" in info:
                self.info["observation_sizes"].append(info["observation_size"])
            if "end_reason" in info: # implies error in query
                self.info["end_reason"] = info["end_reason"]
            if done: # implies submit action
                break
            else:
                if "llama" in self.model:
                    self.messages.append({"role": "user", "content": f"Salesforce instance output: {obs}"})
                else:
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": message["tool_calls"][0]["id"].strip(),
                            "name": action["name"],
                            "content": obs
                        }
                    )
        
        # Here when either max_turns is reached or submitted
        if not done: 
            if "end_reason" not in info: # no error in last query
                message_content = message.get("content")
                if not isinstance(message_content, str):
                    message_content = ""
                self.info["end_reason"] = {
                    "source": "agent",
                    "message": "Max turns reached",
                    "content": message_content.strip()
                }
        self.info["usage"] = self.usage
        self.info["total_cost"] = sum(self.usage["cost"])
        self.info["num_turns"] = turn_id + 1
        return reward

    def get_messages(self) -> List[Dict[str, str]]:
        return self.messages

    def message_action_parser(self, message: str) -> Dict[str, str]:
        if "llama" in self.model:
            parsed_output = self.base_action_parser(message["content"].strip())
            action = {}
            # no tool call and non-null message
            if len(parsed_output) == 1 and parsed_output[0]:
                action["name"] = "respond"
                action["arguments"] = parsed_output[0]
                return action
            # proper tool call
            if len(parsed_output) == 2 and parsed_output[0] and parsed_output[1]:
                action["name"], action["arguments"] = parsed_output
                action["arguments"] = json.loads(action["arguments"])
                return action
            # invalid
            else:
                return None
        
        if "tool_calls" in message and message["tool_calls"] is not None and len(message["tool_calls"]) > 0 and message["tool_calls"][0]["function"] is not None:
            tool_call = message["tool_calls"][0]
            try:
                return {
                    "name": tool_call["function"]["name"].strip(),
                    "arguments": json.loads(tool_call["function"]["arguments"].strip()),
                }
            except json.JSONDecodeError:
                pass

        # Gemini compatibility fallback: some OpenAI-compatible adapters
        # return a plain-text tool directive like:
        #   `Tool call: tool_name({"arg":"value"})`
        # instead of structured `tool_calls`. Parse that format so the
        # agent loop can still progress.
        content = message.get("content")
        if isinstance(content, str):
            tc_match = re.match(r"^\s*Tool call:\s*([a-zA-Z0-9_]+)\((.*)\)\s*$", content, re.DOTALL)
            if tc_match:
                name, args_raw = tc_match.groups()
                try:
                    parsed_args = json.loads(args_raw.strip())
                    if isinstance(parsed_args, dict):
                        return {"name": name.strip(), "arguments": parsed_args}
                except json.JSONDecodeError:
                    pass

        return None


    def base_action_parser(self, model_response):
        try:
            model_response = model_response.strip()
            origin_response = model_response
            action, action_input = None, None
            if 'Action:' in model_response:
                # try based on regex for action, action input
                action_pattern = r"Action:\s*(\w+)"
                action_match = re.search(action_pattern, model_response)
                action = action_match.group(1) if action_match else None
                if "Action Input:" in model_response:
                    action_input_match = model_response.split("Action Input:")[1].strip()
                    # if ```json``` is present, extract json content
                    pattern = r"```(?:json\s*)?\n*(\{.*?\})\n*```"
                    match = re.search(pattern, action_input_match, re.DOTALL)
                    if match:
                        action_input_match = match.group(1)
                    try:
                        action_input = json.loads(action_input_match) # load directly as json
                    except json.JSONDecodeError:
                        try:
                            action_input = ast.literal_eval(action_input_match)  # load as python object
                        except:
                            print('AST also failed')
                            pass
                if action_input is not None:
                    action_input = json.dumps(action_input) # cast to valid json string
                print("----", flush=True)
                print("\tAction:", action, flush=True)
                print("\tAction Input:", action_input, flush=True)
                print("----", flush=True)
            else:
                # assuming this is responding to the user
                return [model_response]
            assert action == None or isinstance(action, str)
            assert action_input == None or isinstance(action_input, str), f"it is {type(action_input)}"
            return [action, action_input]
        except:
            traceback.print_exc()
            return [None, None]
    
## custom llama parser
def parse_tool_response(response: str):
    function_regex = r"<function=(\w+)>(.*?)</function>"
    match = re.search(function_regex, response)
    if match:
        function_name, args_string = match.groups()
        try:
            args = json.loads(args_string)
            return {
                "function": function_name,
                "arguments": args,
            }
        except json.JSONDecodeError as error:
            print(f"Error parsing function arguments: {error}")
            return None
    return None
