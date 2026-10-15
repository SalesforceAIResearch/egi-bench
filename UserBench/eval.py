import os
import re
import json
import time
import argparse
import logging
import yaml
import copy
from openai import AsyncOpenAI
import pandas as pd
import asyncio
import hashlib

from travelgym._token_utils import chat_completion_token_kwargs

# Match HERB's behavior: emit one log line per outbound HTTP call (the
# tested-model client and the TravelGym evaluator) so the per-benchmark log
# captures which gateway each request hits. httpcore stays at WARNING to
# avoid pages of low-level connection-pool noise.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logging.getLogger("httpx").setLevel(logging.INFO)
logging.getLogger("httpcore").setLevel(logging.WARNING)

DEFAULT_ENVS = ["travel22", "travel33", "travel44"]

MAX_WORKER_NUM = int(os.environ.get("MAX_WORKER_NUM", 25))
semaphore = asyncio.Semaphore(MAX_WORKER_NUM)
ROLLOUT_STEP_TIMEOUT_SECONDS = float(os.environ.get("ROLLOUT_STEP_TIMEOUT_SECONDS", "20"))

os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "")


def _extract_openai_compat_tool_args(response):
    """Parse tool-call args from an OpenAI-style response with text fallback.

    Returns ``(json_args, tool_call_or_none)`` where ``tool_call_or_none`` is
    the structured tool_call object when the model returned one, or ``None``
    when args were recovered from a plain-text "Tool call: name({...})"
    fallback (some Gemini-backed OpenAI-compat gateways do this).
    """
    msg = response.choices[0].message
    if getattr(msg, "tool_calls", None):
        tool_call = msg.tool_calls[0]
        args = tool_call.function.arguments
        json_args = json.loads(args) if isinstance(args, str) else args
        return json_args, tool_call

    content = getattr(msg, "content", None)
    if isinstance(content, str):
        m = re.match(r"^\s*Tool call:\s*[a-zA-Z0-9_]+\((.*)\)\s*$", content, re.DOTALL)
        if m:
            return json.loads(m.group(1).strip()), None
    raise ValueError(f"Invalid response (response without tool call detected): {response}")
    
async def load_data(env_name, one_choice=False):
    # Use environment variable for data path, default to local data directory
    data_root = os.environ.get("TRAVELGYM_DATA_PATH", "./data")
    if one_choice and "travel" in env_name:
        path = f"{data_root}/{env_name}_multiturn_onechoice/test.parquet"
    else:
        path = f"{data_root}/{env_name}_multiturn/test.parquet"
    df = pd.read_parquet(path)
     # turn into a list of data, using only the prompt
    data = []
    for i in range(len(df)):
        data.append({
            "env_name": env_name,
            "gold": str(df.iloc[i]["reward_model"]["id"]) if (env_name == "intention" or env_name == "persuasion" or "travel" in env_name) else str(df.iloc[i]["reward_model"]["title"]),
            "messages": list(df.iloc[i]["prompt"]),
        })
    return data


async def build_env(data, max_turns, one_choice, wrong_choice_number, noise_choice_number):
    gold = data["gold"]
    env_name = data["env_name"]
    print("Building environment...", env_name)
    if "travel" in env_name:
        import travelgym
        config = travelgym.get_default_config()
        config.max_steps = max_turns
        config.data_mode = "single"
        config.data_source = gold
        config.wrong_choice_number = wrong_choice_number
        config.noise_choice_number = noise_choice_number
        # configure the one choice option
        config.one_choice_per_aspect = one_choice
        env = travelgym.TravelEnv(config=config)
        env.reset()
        return env
    else:
        raise ValueError(f"Environment {env_name} not supported")


async def gen_response(client, data, schema, temperature, model_name):
    # Single OpenAI-compat path. The runner points us at the LiteLLM proxy, which
    # speaks OpenAI Chat Completions on the wire and translates to the
    # native upstream parameters per provider:
    #   * OpenAI reasoning (o1/o3/o4/gpt-5*) → ``max_completion_tokens``
    #   * OpenAI non-reasoning              → ``max_tokens``
    #   * Claude (Bedrock)                  → ``inferenceConfig.maxTokens``
    #   * Gemini                            → ``max_output_tokens``
    # Reasoning-family detection (Claude 3.7 / 4.x, Gemini 2.5 / 3, plus
    # the OpenAI families) lives in ``travelgym/_token_utils.py``; we just
    # send the bumped cap and let the proxy forward it.
    for _ in range(10):
        try:
            completion_params = {
                "model": model_name,
                "messages": data["messages"],
                "tools": [schema],
                "tool_choice": "required" if str(os.environ.get("TOOL_CHOICE", "required")) == "required" else "auto",
                "temperature": temperature,
                "n": 1,
            }
            token_kwargs = chat_completion_token_kwargs(model_name)
            try:
                response = await client.chat.completions.create(
                    **completion_params, **token_kwargs
                )
            except TypeError:
                # Very old SDKs/servers that only know ``max_tokens``.
                cap = next(iter(token_kwargs.values()))
                response = await client.chat.completions.create(
                    **completion_params, max_tokens=cap
                )
            return response

        except Exception as e:
            print(f"[local tool call] failed: {e}")
            time.sleep(2)

    print(f"[local tool call] failed ten times, please check the model name and API key.")
    raise RuntimeError("!!! Local function_call failed ten times !!!")


def hash(data):
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()

async def rollout(data, client, function, temperature, max_turns, model_name, one_choice, wrong_choice_number, noise_choice_number):
    turn = 0
    rewards = []
    hash_id = hash(data)
    history = []
    # Allow the model a small number of recoverable misses (no tool_call
    # emitted, or tool_call with missing fields) before aborting the rollout.
    # Previously a single miss raised ``assert False`` and failed the whole
    # rollout, which bit ``gemini-2.0-flash`` hard when it occasionally
    # returned an empty response or prose narration instead of a tool call.
    _MAX_TOOL_CALL_MISSES = 3
    tool_call_misses = 0

    def _nudge_and_continue(reason: str) -> bool:
        """Append a user-role nudge to the conversation and bump the miss
        counter. Returns True if we should retry, False if we've hit the cap."""
        nonlocal tool_call_misses
        tool_call_misses += 1
        if tool_call_misses >= _MAX_TOOL_CALL_MISSES:
            return False
        data["messages"].append(
            {
                "role": "user",
                "content": (
                    f"The previous response was invalid ({reason}). "
                    "You MUST call the provided tool with fields "
                    "``choice``, ``content`` and ``thought`` to continue."
                ),
            }
        )
        return True

    try:
        env = await build_env(data, max_turns, one_choice, wrong_choice_number, noise_choice_number)
        while turn < max_turns:
            response = await gen_response(client, data, function, temperature, model_name)
            try:
                json_args, tool_call = _extract_openai_compat_tool_args(response)
            except Exception:
                if _nudge_and_continue("no tool_call emitted"):
                    continue
                assert False, f"Invalid response (response without tool call detected): {response}"

            if not (
                isinstance(json_args, dict)
                and "choice" in json_args
                and "content" in json_args
                and "thought" in json_args
            ):
                if _nudge_and_continue("tool_call missing required fields"):
                    continue
                assert False, f"Invalid response: {json_args}"
            tool_call_misses = 0

            choice = json_args["choice"]
            content = json_args["content"]
            if choice == "action" and not content.startswith("[action]"):
                formatted_action = "[action] " + content
            elif choice == "answer" and not content.startswith("[answer]"):
                formatted_action = "[answer] " + content
            elif choice == "search" and not content.startswith("[search]"):
                formatted_action = "[search] " + content
            else:
                formatted_action = content

            observation, reward, terminated, truncated, info = await asyncio.wait_for(
                env.step_async(formatted_action),
                timeout=ROLLOUT_STEP_TIMEOUT_SECONDS
            )
            feedback = observation["feedback"]

            if len(feedback) > 512 and choice == "search":
                output_feedback = feedback[:256] + "  ... ... " + feedback[-256:]
            else:
                output_feedback = feedback
            
            print(f"In {data['env_name']}, turn {turn}, action: {formatted_action}, feedback: {output_feedback}, reward: {reward}")
            rewards.append(reward)

            history.append({
                "turn": turn,
                "choice": choice,
                "content": content,
                "feedback": feedback,
                "reward": reward,
                "passive_elicited_preferences": observation.get("passive_elicited_preferences", 0),
                "active_elicited_preferences": observation.get("active_elicited_preferences", 0),
            })

            if terminated or truncated:
                break

            if tool_call is not None:
                data["messages"].append({"role": "assistant", "tool_calls": [tool_call]})
                data["messages"].append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": feedback,
                    }
                )
            else:
                # Gemini-text fallback: gateway returned ``Tool call: ...`` as
                # plain content. Replay the assistant turn as plain text and
                # the env feedback as a user message so the next request
                # remains structurally valid OpenAI chat history.
                assistant_text = response.choices[0].message.content or json.dumps(json_args)
                data["messages"].append({"role": "assistant", "content": assistant_text})
                data["messages"].append({"role": "user", "content": f"Tool result: {feedback}"})
            turn += 1
            
        total_reward = rewards
        return {"hash_id": hash_id, "reward": total_reward, "history": history}
    
    except asyncio.TimeoutError:
        print(f"==================== [local] rollout timeout !!! ====================")
        total_reward = rewards if len(rewards) > 0 else [0]
        return {"hash_id": hash_id, "reward": total_reward, "history": history}
    
    except Exception as e:
        print(f"==================== [local] rollout failed: {e} ====================")
        total_reward = rewards if len(rewards) > 0 else [0]
        return {"hash_id": hash_id, "reward": total_reward, "history": history}


async def post_process_results(results, reward_cache, env, pass_k):
    if "travel" in env:
        results[env][str(pass_k)] = {}
        number_of_1 = []
        number_of_08 = []
        micro_avg = []
        micro_max = []
        for hash_id in reward_cache[env]:
            turn_scores = reward_cache[env][hash_id]["reward"][-1]
            number_of_1.append(turn_scores.count(1.0)) # best choice
            number_of_08.append(turn_scores.count(0.8)) # correct choice
            micro_avg.append(sum(turn_scores) / len(turn_scores) if len(turn_scores) > 0 else 0)
            micro_max.append(max(turn_scores) if len(turn_scores) > 0 else 0)
        results[env][str(pass_k)]["micro_avg"] = sum(micro_avg) / len(micro_avg)
        results[env][str(pass_k)]["micro_max"] = sum(micro_max) / len(micro_max)
        results[env][str(pass_k)]["avg_number_of_08"] = sum(number_of_08) / len(number_of_08)
        results[env][str(pass_k)]["avg_number_of_1"] = sum(number_of_1) / len(number_of_1)
        print(f"\n ######### Pass {pass_k} reward: {results[env][str(pass_k)]['micro_max']} ######### \n")
    return results


async def limited_rollout(*args, **kwargs):
    async with semaphore:
        return await rollout(*args, **kwargs)
    

async def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--model_name", type=str, default="Qwen2.5-7B-Instruct")
    arg_parser.add_argument("--port", type=int, default=8000)
    arg_parser.add_argument("--max_turns", type=int, default=8)
    arg_parser.add_argument("--pass_k", type=int, nargs="+", default=[1])
    arg_parser.add_argument("--temperature", type=float, default=1.0)
    arg_parser.add_argument("--envs", type=str, nargs="+", default=DEFAULT_ENVS)
    arg_parser.add_argument("--save_name", type=str, default="results")
    arg_parser.add_argument("--one_choice", type=bool, default=False)
    arg_parser.add_argument("--wrong_choice_number", type=int, default=10)
    arg_parser.add_argument("--noise_choice_number", type=int, default=5)
    arg_parser.add_argument(
        "--max_tasks_per_env",
        type=int,
        default=None,
        help="If set, keep only the first N tasks from each env (useful for quick mode).",
    )

    args = arg_parser.parse_args()

    print(args)
    
    PROJECT_ROOT = os.environ.get("PROJECT_ROOT", ".")

    # The tested-model client always points at the local LiteLLM proxy on
    # ``--port``. The proxy exposes a single OpenAI-compat surface and
    # translates upstream to Bedrock / Gemini / OpenAI / vLLM as needed.
    # Passing ``base_url`` explicitly overrides any ``OPENAI_BASE_URL`` set
    # in the env -- which the parent runner sets to the real-OpenAI endpoint
    # so the TravelGym gym evaluator (constructed without an explicit
    # base_url in prompts.py / prompt_async.py) keeps going to OpenAI for
    # grading.
    base_url = f"http://localhost:{args.port}/v1"
    client = AsyncOpenAI(api_key="dummy", base_url=base_url)

    function = yaml.safe_load(open(f"{PROJECT_ROOT}/schema/interact_tool.yaml", "r"))["tool_schema"]

    # ``args.save_name`` may legitimately contain ``/`` (callers sometimes pass
    # the raw provider-prefixed model id). Make sure the parent directory of
    # every cache/result file we write actually exists, otherwise downstream
    # ``open(..., "w")`` calls die with ``FileNotFoundError`` after the first
    # successful rollout.
    results_path = f"{PROJECT_ROOT}/outputs/results_{args.save_name}.json"
    reward_cache_path = f"{PROJECT_ROOT}/outputs/reward_cache_{args.save_name}.json"
    os.makedirs(os.path.dirname(results_path), exist_ok=True)
    os.makedirs(os.path.dirname(reward_cache_path), exist_ok=True)
    if os.path.exists(results_path):
        results = json.load(open(results_path, "r"))
    else:
        results = {}
    if os.path.exists(reward_cache_path):
        reward_cache = json.load(open(reward_cache_path, "r"))
    else:
        reward_cache = {}
    
    for env in args.envs:
        print(f"Evaluating {env}...")
        data = await load_data(env, args.one_choice)
        if args.max_tasks_per_env is not None and args.max_tasks_per_env > 0:
            data = data[: args.max_tasks_per_env]
            print(f"  (limited to first {len(data)} tasks via --max_tasks_per_env)")
        if env not in results:
            results[env] = {}
        if env not in reward_cache:
            reward_cache[env] = {}
        
        for pass_k in args.pass_k:
            # Check task-level coverage instead of env-level. A previous run
            # (e.g. quick mode with --max_tasks_per_env 60) may have populated
            # results[env][pass_k] using only a subset of ``data``; in deep
            # mode ``data`` is the full task set and we need to extend the
            # cache to the new tasks. Only short-circuit when every task in
            # ``data`` already has >= pass_k rollouts cached.
            data_ids = [hash(d) for d in data]
            already_covered = all(
                data_id in reward_cache[env]
                and len(reward_cache[env][data_id]["reward"]) >= pass_k
                for data_id in data_ids
            )
            if already_covered and str(pass_k) in results[env]:
                print(f"Pass {pass_k} already evaluated for all {len(data)} tasks, skipping...")
                continue

            reqs = []
            # use limited rollout to avoid getting stuck
            for d, data_id in zip(data, data_ids):
                existing_number = len(reward_cache[env][data_id]["reward"]) if data_id in reward_cache[env] else 0
                needed_number = max(0, pass_k - existing_number)
                if needed_number == 0:
                    continue
                for _ in range(needed_number):
                    reqs.append(
                        limited_rollout(copy.deepcopy(d), client, function, args.temperature, args.max_turns, args.model_name, args.one_choice, args.wrong_choice_number, args.noise_choice_number)
                    )

            if reqs:
                print(f"Running {len(reqs)} new rollouts for {env} (pass_k={pass_k}); cache had {sum(1 for did in data_ids if did in reward_cache[env])}/{len(data)} tasks.")
            else:
                print(f"All {len(data)} tasks already have pass_k={pass_k} rollouts cached; recomputing aggregate metrics from cache.")

            # Run all rollouts in parallel; persist the reward cache after each
            # completed rollout so a mid-run kill (e.g. timeout) still leaves
            # all finished tasks on disk.  A subsequent run detects the cache
            # and skips already-completed tasks via the ``already_covered``
            # check above, enabling crash-safe resumption.
            futures = [asyncio.ensure_future(req) for req in reqs]
            for fut in asyncio.as_completed(futures):
                try:
                    r = await fut
                except Exception as e:
                    print(f"[userbench] rollout failed: {e}")
                    continue
                hash_id = r["hash_id"]
                if hash_id not in reward_cache[env]:
                    reward_cache[env][hash_id] = {"history": [], "reward": []}
                reward_cache[env][hash_id]["history"].append(r["history"])
                reward_cache[env][hash_id]["reward"].append(r["reward"])
                with open(f"{PROJECT_ROOT}/outputs/reward_cache_{args.save_name}.json", "w") as f:
                    json.dump(reward_cache, f, indent=4)

            # Post-process the results
            results = await post_process_results(results, reward_cache, env, pass_k)

            with open(f"{PROJECT_ROOT}/outputs/results_{args.save_name}.json", "w") as f:
                json.dump(results, f, indent=4)
            with open(f"{PROJECT_ROOT}/outputs/reward_cache_{args.save_name}.json", "w") as f:
                json.dump(reward_cache, f, indent=4)
        

if __name__ == "__main__":
    asyncio.run(main())
