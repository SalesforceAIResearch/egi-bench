from dotenv import load_dotenv
import json, os
import logging
import random
from crm_sandbox.agents import ChatAgent, ToolCallAgent
from crm_sandbox.agents.utils import BEDROCK_MODELS_MAP, TOGETHER_MODELS_MAP, VERTEX_MODELS_MAP
from crm_sandbox.data.assets import TASKS_ORIGINAL, SCHEMA_ORIGINAL, TASKS_B2B, TASKS_B2B_INTERACTIVE, TASKS_B2C, TASKS_B2C_INTERACTIVE, B2B_SCHEMA, B2C_SCHEMA, EXTERNAL_FACING_TASKS
from crm_sandbox.env.env import ChatEnv, ToolEnv, InteractiveChatEnv
from crm_sandbox.env import TOOLS, TOOLS_FULL
import traceback
import argparse
from datetime import datetime
import time

# Emit one concise line per OpenAI-compatible HTTP request, e.g.
# ``HTTP Request: POST http://localhost:8008/v1/... "HTTP/1.1 200 OK"``.
# run_all.py already captures stdout+stderr into the per-benchmark log file.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logging.getLogger("httpx").setLevel(logging.INFO)
logging.getLogger("httpcore").setLevel(logging.WARNING)

def run():
    if not os.path.exists(args.log_dir):
        os.makedirs(args.log_dir)
    # ``args.model`` may include path separators (e.g. ``vertex/gemini-2.5-flash``,
    # ``bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0``). Naively interpolating
    # such names into ``ckpt_path`` produces a phantom subdirectory
    # (``results_vertex/gemini-2.5-flash_…``) whose parent isn't created by the
    # ``os.makedirs(args.log_dir)`` above, so every checkpoint write fails with
    # ``FileNotFoundError`` and the per-task results are silently lost.
    safe_model = args.model.replace("/", "_").replace(":", "_")
    ckpt_path = f"{args.log_dir}/results_{safe_model}_{args.agent_strategy}_{args.task_category}.json"
    if args.org_type == "b2b":
        TASKS_NATURAL = TASKS_B2B_INTERACTIVE if args.interactive else TASKS_B2B
        SCHEMA = B2B_SCHEMA
    elif args.org_type == "b2c":
        TASKS_NATURAL = TASKS_B2C_INTERACTIVE if args.interactive else TASKS_B2C
        SCHEMA = B2C_SCHEMA
    else:
        # the original CRMArena
        TASKS_NATURAL = TASKS_ORIGINAL
        SCHEMA = SCHEMA_ORIGINAL
    
    if args.task_category == "all":
        selected_tasks = TASKS_NATURAL
    elif "," in args.task_category:
        selected_tasks = [task for task in TASKS_NATURAL if task["task"] in args.task_category.split(",")]
    else:
        selected_tasks = [task for task in TASKS_NATURAL if task["task"] == args.task_category]

    # Optional bounded sampling for runtime control.
    if args.max_tasks_per_category and args.max_tasks_per_category > 0:
        grouped = {}
        for task in selected_tasks:
            grouped.setdefault(task["task"], []).append(task)

        sampled = []
        rng = random.Random(args.sample_seed)
        for _, tasks in grouped.items():
            if len(tasks) <= args.max_tasks_per_category:
                sampled.extend(tasks)
            else:
                sampled.extend(rng.sample(tasks, args.max_tasks_per_category))
        selected_tasks = sampled
        
    # Load checkpoint if it exists
    completed_tasks = {}
    
    if os.path.exists(ckpt_path):
        if args.reuse_results:
            with open(ckpt_path, 'r') as f:
                completed_tasks = {task['task_id']: task for task in json.load(f)}
        else:
            os.remove(ckpt_path)
            
    print(f"Loaded {len(selected_tasks)} tasks")
    start_time = datetime.now()
    print(f"Starting evaluation at {start_time}")
    selected_tasks = {t['idx']: t for t in selected_tasks}
    
    if args.agent_strategy in ["act", "react"]:
        if args.interactive:
            if args.agent_strategy == "act":
                raise ValueError(
                    "Interactive mode is only supported for the 'react' strategy. "
                    "'act' strategy cannot be used with --interactive."
                )
            # This implies agent_strategy is "react" if interactive is True
            
            env = InteractiveChatEnv(tasks=selected_tasks, max_user_turns=args.max_user_turns, org_type=args.org_type)
        else: # Not interactive, both 'act' and 'react' are fine
            env = ChatEnv(tasks=selected_tasks, org_type=args.org_type)
    elif args.agent_strategy == "tool_call":
        if args.interactive:
            raise NotImplementedError(
                f"Interactive mode is not supported for the '{args.agent_strategy}' strategy."
            )
        if args.org_type != "original":
            raise NotImplementedError(
                f"The '{args.agent_strategy}' strategy is only supported for the 'original' org_type (CRMArena), "
                f"not '{args.org_type}'."
            )
        env = ToolEnv(tools=TOOLS, tasks=selected_tasks, org_type=args.org_type)
    elif args.agent_strategy == "tool_call_flex":
        if args.interactive:
            raise NotImplementedError(
                f"Interactive mode is not supported for the '{args.agent_strategy}' strategy."
            )
        if args.org_type != "original":
            raise NotImplementedError(
                f"The '{args.agent_strategy}' strategy is only supported for the 'original' org_type (CRMArena), "
                f"not '{args.org_type}'."
            )
        env = ToolEnv(tools=TOOLS_FULL, tasks=selected_tasks, org_type=args.org_type)
    else:
        # Fallback for unknown strategies, though argparse choices should prevent this.
        raise ValueError(f"Unsupported agent_strategy: {args.agent_strategy}")
    for idx, task in selected_tasks.items():
        # Skip tasks that have already been completed
        if idx in completed_tasks:
            print(f"Skipping task {idx} (already completed)")
            continue
        if task["task"] in EXTERNAL_FACING_TASKS:
            agent_type = "external"
        else:
            agent_type = "internal"
        if args.agent_strategy in ["react"]:
            agent = ChatAgent(
                model=args.model,
                schema_obj=SCHEMA,
                eval_mode=args.agent_eval_mode,
                max_turns=args.max_turns,
                strategy=args.agent_strategy,
                provider=args.llm_provider,
                interactive=args.interactive,
                agent_type=agent_type,
                privacy_aware_prompt=args.privacy_aware_prompt,
                base_url=args.base_url,
            )
        else:
            agent = ToolCallAgent(
                model=args.model,
                tools=env.tools_info,
                schema_obj=SCHEMA,
                eval_mode=args.agent_eval_mode,
                max_turns=args.max_turns,
                strategy=args.agent_strategy,
                provider=args.llm_provider,
                base_url=args.base_url,
            )
        print(f"Running task {idx}")
        try:
            reward = agent.act(
                env,
                idx
            )
            result = {
                "task_id": idx,
                "task_type": task["task"],
                "gt_answer": task["answer"],
                "reward": reward,
                "agent_info": agent.info,
                "traj": agent.get_messages(),
            }
        except Exception as e:
            traceback.print_exc()
            result = {
                "task_id": idx,
                "task_type": task["task"],
                "gt_answer": task["answer"],
                "reward": 0,
                "agent_info": {
                    "source": "api",
                    "content": "Error: " + str(e)
                },
                "traj": agent.get_messages(),
            }
        print(
            "✅" if result["reward"] == 1 else "❌",
            f"task_id={idx}"
        )
        print("-----")
        data_res = []
        if os.path.exists(ckpt_path):
            with open(ckpt_path, "r") as f:
                data_res = json.load(f)
        with open(ckpt_path, "w") as f:
            json.dump(data_res + [result], f, indent=2)
        time.sleep(1)
    end_time = datetime.now()
    print(f"Finished evaluation at {end_time}")
    
if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        type=str,
        help="The model to use for the agent",
        default="o1-mini",
        choices = ["o1-mini", "gpt-4o", "gpt-4-turbo"].extend(BEDROCK_MODELS_MAP.keys()),
    )
    parser.add_argument(
        "--agent_strategy",
        type=str,
        default="react",
        choices=["tool_call", "act", "react", "tool_call_flex"],
    )
    parser.add_argument(
        "--agent_eval_mode",
        type=str,
        default="default",
        choices=["default", "aided"],
    )
    parser.add_argument(
        "--llm_provider",
        type=str,
        default="bedrock",
        choices=["bedrock", "together_ai", "openai", "vertex_ai"]
    )
    parser.add_argument(
        "--task_category",
        type=str,
        default="all",
        choices=[
            "handle_time", "transfer_count", "knowledge_qa", "best_region_identification", 
            "case_routing", "named_entity_disambiguation", "policy_violation_identification", 
            "top_issue_identification", "monthly_trend_analysis", 
            "sales_amount_understanding", "lead_routing", "sales_cycle_understanding", 
            "conversion_rate_comprehension", "wrong_stage_rectification", "sales_insight_mining", 
            "quote_approval", "lead_qualification", "activity_priority", "invalid_config", 
            'private_customer_information', 'internal_operation_data', 'confidential_company_knowledge', 
            "all"
        ],
        help="The category of tasks to evaluate (comma separated)",
    )
    parser.add_argument(
        "--max_turns",
        type=int,
        default=20
    )
    parser.add_argument(
        "--max_user_turns",
        type=int,
        default=10
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Enable interactive mode"
    )
    parser.add_argument(
        "--org_type",
        type=str,
        default="b2b",
        choices=["b2b", "b2c", "original"] # original is the original CRMArena
    )
    parser.add_argument(
        "--reuse_results",
        action="store_true",
        help="Reuse results from previous runs"
    )
    parser.add_argument(
        "--privacy_aware_prompt",
        type=lambda x: {'true': True, 'false': False}[x.lower()],
        default=False,
        help="Whether to use a privacy-aware prompt. Accepts 'true' or 'false'. (default: %(default)s)"
    )
    parser.add_argument("--log_dir", type=str, default="logs")
    parser.add_argument(
        "--base_url",
        type=str,
        default=None,
        help=(
            "Custom OpenAI-compatible API base URL (e.g. http://localhost:8000/v1). "
            "When set, all LLM calls are routed to this endpoint instead of the "
            "provider-specific backend, and the model name is passed through unchanged."
        ),
    )
    parser.add_argument(
        "--max_tasks_per_category",
        type=int,
        default=0,
        help="If > 0, sample at most this many tasks per category",
    )
    parser.add_argument(
        "--sample_seed",
        type=int,
        default=42,
        help="Random seed used when sampling tasks",
    )
    args = parser.parse_args()
    print(args)

    run()
    