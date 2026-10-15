from react import MyRAG
import json
import os
import csv
import pickle
from metadata_search_functions import finish_agent
from llama_index.core import QueryBundle
from react import CONTEXT_AGENT
from llama_index.core.agent.workflow import ReActAgent
from llama_index.core.workflow import Context
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import uuid
import io
import contextlib
import glob
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_dataset(mode):
    if mode == "ans":
        return {
            "answer": [],
            "ground_truth": [],
            "question": [],
            "citations": [],
            "type": [],
        }
    return {
        "answer": [],
        "question": [],
    }


def save_checkpoint(checkpoint_file, dataset, processed_ids, start_time, total_questions):
    checkpoint_payload = {
        "dataset": dataset,
        "processed_ids": list(processed_ids),
        "elapsed_time": time.time() - start_time,
        "total_questions": total_questions,
    }
    with open(checkpoint_file, "wb") as f:
        pickle.dump(checkpoint_payload, f)


def load_checkpoint(checkpoint_file):
    with open(checkpoint_file, "rb") as f:
        payload = pickle.load(f)

    # Backward compatibility: output file may only contain the dataset dict.
    if isinstance(payload, dict) and "dataset" not in payload and "question" in payload:
        questions = payload.get("question", [])
        return {
            "dataset": payload,
            "processed_ids": [],
            "processed_questions_legacy": questions if isinstance(questions, list) else [],
            "elapsed_time": 0.0,
            "total_questions": len(questions) if isinstance(questions, list) else 0,
        }

    if not isinstance(payload, dict):
        raise ValueError("Checkpoint payload must be a dict.")
    if "dataset" not in payload:
        raise ValueError("Checkpoint missing required fields.")

    if "processed_ids" not in payload:
        # Legacy checkpoint compatibility.
        payload["processed_ids"] = []
        payload["processed_questions_legacy"] = payload.get("processed_questions", [])

    return payload


DEFAULT_MAX_ITERATIONS = 10


async def run_agent_async(agent, question, max_iterations=DEFAULT_MAX_ITERATIONS):
    """Helper to run agent query asynchronously.

    ``max_iterations`` is passed through to the workflow runtime, which
    pops it from kwargs (see llama-index ``multi_agent_workflow.py``).
    Default 10 mirrors the original HERB benchmark configuration.
    """
    ctx = Context(agent)
    handler = agent.run(question, ctx=ctx, max_iterations=max_iterations)
    response = await handler
    return response


def _coerce_answer_to_text(answer):
    # Persisting the raw LlamaIndex AgentOutput / response object embeds objects
    # like ``AttributedDict`` whose ``__init__`` is not pickle round-trip safe in
    # current llama-index-instrumentation versions, breaking ``evaluate.py``'s
    # ``pickle.load`` step on a fresh venv. Store plain text (or ``None`` for
    # refusals/timeouts) so checkpoints and final pickles always re-load.
    if answer is None or isinstance(answer, str):
        return answer
    text = getattr(answer, "response", None)
    if isinstance(text, str):
        return text
    return str(answer)


def process_question(args):
    item_id, question, myrag, data, num_attempts, mode = args
    # Restore the upstream HERB ReAct configuration after the
    # llama-index 0.14 migration: ``contexts=`` was renamed to
    # ``system_prompt=`` (constructor) and ``max_iterations=`` moved
    # from the constructor to ``.run()``. Both are required to match
    # the original benchmark semantics.
    agent = ReActAgent(
        tools=myrag.tools,
        llm=myrag.llm,
        system_prompt=CONTEXT_AGENT,
        # verbose=True,
    )
    
    if mode == "ans":
        response = {
            "item_id": item_id,
            "question": question,
            "answer": None,
            "ground_truth": data["ground_truth"],
            "citations": data["citations"],
            "type": data["type"]
        }
    else:  # unans mode
        response = {
            "item_id": item_id,
            "question": question,
            "answer": None
        }

    for attempt in range(num_attempts):
        try:
            logger.info(f">>>>>>>>> QUESTION >>>>>>>>>>> {question}")
            logger.info(f">>>>>>>>> ATTEMPT >>>>>>>>>>> {attempt}")
            f = io.StringIO()
            with contextlib.redirect_stdout(f):
                answer = asyncio.run(
                    run_agent_async(agent, question, max_iterations=DEFAULT_MAX_ITERATIONS)
                )
            logger.info(f">>>>>>>>> ANSWER >>>>>>>>>>> {answer}")
            done = finish_agent(question, answer)
            if done:
                response["answer"] = _coerce_answer_to_text(answer)
                return response
            
            # Reset agent if attempt failed
            agent = ReActAgent(
                tools=myrag.tools,
                llm=myrag.llm,
                system_prompt=CONTEXT_AGENT,
                # verbose=True,
            )
            
        except Exception as e:
            logger.exception(
                "Error processing question with ReAct agent (%s): %r",
                type(e).__name__,
                e,
            )
            continue
    
    try:
        fallback_answer = myrag.fallback_answer(question)
        if fallback_answer:
            response["answer"] = _coerce_answer_to_text(fallback_answer)
    except Exception as e:
        logger.exception(
            "Error processing question with fallback agent (%s): %r",
            type(e).__name__,
            e,
        )
    return response

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["ans", "unans"],
        default="ans",
        help="Mode to run in: 'ans' for answerable questions, 'unans' for unanswerable questions",
    )
    parser.add_argument(
        "--embedding_model_name",
        type=str,
        default="text-embedding-3-large",
        help="Name of the embedding model to use",
    )
    parser.add_argument(
        "--embedding_mode",
        choices=["openai", "huggingface"],
        default="openai",
        help="Embedding mode to use (openai or huggingface)",
    )
    parser.add_argument(
        "--chunk_size",
        default=256,
        type=int,
        help="Size of text chunks for processing",
    )
    parser.add_argument(
        "--chunk_overlap",
        default=32,
        type=int,
        help="Overlap between consecutive chunks",
    )
    parser.add_argument(
        "--max_workers",
        default=5,
        type=int,
        help="Number of parallel workers to use",
    )
    parser.add_argument(
        "--model_name",
        type=str,
        default="gpt-4o"
        # gemini-2.5-flash
    )   # deepseek-ai/DeepSeek-V3 meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8 Qwen/Qwen3-235B-A22B-fp8-tput meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo deepseek-ai/DeepSeek-R1 Qwen/Qwen2.5-72B-Instruct-Turbo Qwen/QwQ-32B meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo
    parser.add_argument(
        "--llm_provider",
        choices=["openai", "togetherai", "gemini"],
        default="openai",
        help="LLM provider to use (openai or togetherai)",
    )
    parser.add_argument(
        "--num_attempts",
        default=1,
        type=int,
        help="Number of attempts to make for each question",
    )
    parser.add_argument(
        "--reuse_index",
        action="store_true",
        help="Reuse existing indices if they exist",
    )
    parser.add_argument(
        "--api_base",
        type=str,
        default=None,
        help="Base URL for OpenAI API (e.g., http://localhost:8008/v1 for the local LiteLLM proxy)",
    )
    parser.add_argument(
        "--context_window",
        type=int,
        default=400000,
        help=(
            "Context window (tokens) advertised to the agent for the OpenAI "
            "LLM provider. Required because HERB uses ``OpenAILike`` to "
            "support arbitrary gateway-routed model names; this value is what "
            "llama-index uses for prompt-window accounting (chunk packing in "
            "CompactAndRefine, etc.). It must be <= the upstream model's "
            "actual window — setting it lower is safe but slightly less "
            "efficient. Default 400000 matches the gpt-5 / gpt-5.1 / gpt-5.2 "
            "base family. Override for: gpt-5.5 / gpt-4.1 -> 1047576; "
            "gpt-4o / gpt-5-chat-latest -> 128000; gpt-3.5-turbo -> 16384."
        ),
    )
    parser.add_argument(
        "--max_questions",
        type=int,
        default=None,
        help="Cap number of questions for quick test runs.",
    )
    parser.add_argument(
        "--checkpoint_every",
        type=int,
        default=25,
        help="Save checkpoint after every N completed questions.",
    )
    parser.add_argument(
        "--resume_checkpoint",
        action="store_true",
        help="Resume from an existing checkpoint/output file if present.",
    )
    args = parser.parse_args()

    os.makedirs("output", exist_ok=True)
    if args.api_base:
        # Force all OpenAI SDK call paths (including helper utilities) through gateway.
        os.environ["OPENAI_BASE_URL"] = args.api_base
        os.environ["OPENAI_API_BASE"] = args.api_base
        # Gateway mode still needs a placeholder key for OpenAI client validation.
        if not os.environ.get("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = "dummy"

    product_dir = "../data/products"
    save_index_path = f"index/{args.embedding_model_name}/all"
    load_index_path = save_index_path if args.reuse_index else None

    myrag = MyRAG(
        product_data=product_dir,
        load_index_path=load_index_path,
        save_index_path=save_index_path,
        embedding_mode=args.embedding_mode,
        embedding_model_name=args.embedding_model_name,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        model_name=args.model_name,
        llm_provider=args.llm_provider,
        api_base=args.api_base,
        context_window=args.context_window,
    )

    product_files = glob.glob(os.path.join(product_dir, "*.json"))
    qa_dataset = []

    for product_file in product_files:
        with open(product_file, 'r') as f:
            product_data = json.load(f)
            product_name = os.path.splitext(os.path.basename(product_file))[0]
            if args.mode == "unans" and "unanswerable_questions" in product_data:
                for idx, question_text in enumerate(product_data["unanswerable_questions"]):
                    qa_dataset.append(
                        {
                            "item_id": f"{product_name}:unans:{idx}",
                            "question": question_text,
                        }
                    )
            elif args.mode == "ans" and "answerable_questions" in product_data:
                for idx, question_data in enumerate(product_data["answerable_questions"]):
                    qa_dataset.append(
                        {
                            "item_id": f"{product_name}:ans:{idx}",
                            **question_data,
                        }
                    )

    safe_embedding_name = args.embedding_model_name.replace("/", "_")
    output_file = (
        f"output/{safe_embedding_name}-"
        f"{args.model_name.replace('/', '_')}-"
        f"{args.num_attempts}-{args.mode}.pk"
    )
    checkpoint_file = f"{output_file}.checkpoint"

    if args.max_questions is not None:
        qa_dataset = qa_dataset[:args.max_questions]

    if args.checkpoint_every < 1:
        raise ValueError("--checkpoint_every must be >= 1")

    dataset = init_dataset(args.mode)
    processed_ids = set()
    processed_questions_legacy = set()

    start_time = time.time()
    processed_count = 0
    processed_since_checkpoint = 0

    if args.resume_checkpoint:
        checkpoint_source = None
        if os.path.exists(checkpoint_file):
            checkpoint_source = checkpoint_file
        elif os.path.exists(output_file):
            checkpoint_source = output_file

        if checkpoint_source:
            try:
                payload = load_checkpoint(checkpoint_source)
                loaded_dataset = payload["dataset"]
                loaded_ids = payload.get("processed_ids", [])
                loaded_legacy_questions = payload.get("processed_questions_legacy", [])
                if (
                    not isinstance(loaded_dataset, dict)
                    or not isinstance(loaded_ids, list)
                    or not isinstance(loaded_legacy_questions, list)
                ):
                    raise ValueError("Invalid checkpoint structure.")
                dataset = loaded_dataset
                processed_ids = set(loaded_ids)
                processed_questions_legacy = set(loaded_legacy_questions)
                if args.mode == "unans" and not processed_ids and processed_questions_legacy:
                    logger.warning(
                        "Legacy resume data detected for unans mode without item IDs; "
                        "ignoring legacy question-based progress to avoid dropping duplicates."
                    )
                    processed_questions_legacy = set()
                previous_elapsed = float(payload.get("elapsed_time", 0.0))
                start_time = time.time() - max(previous_elapsed, 0.0)
                logger.info(
                    "Resuming from %s with %d completed items.",
                    checkpoint_source,
                    len(processed_ids) or len(processed_questions_legacy),
                )
            except Exception as e:
                logger.warning("Failed to resume from %s: %s", checkpoint_source, e)

    qa_dataset = [
        data
        for data in qa_dataset
        if data["item_id"] not in processed_ids and data["question"] not in processed_questions_legacy
    ]
    total_questions = len(qa_dataset) + max(len(processed_ids), len(processed_questions_legacy))
    logger.info(
        "Loaded %d pending questions (%d already completed).",
        len(qa_dataset),
        max(len(processed_ids), len(processed_questions_legacy)),
    )

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        tasks = [
            (data["item_id"], data["question"], myrag, data, args.num_attempts, args.mode)
            for data in qa_dataset
        ]

        futures = [executor.submit(process_question, task) for task in tasks]

        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing questions"):
            try:
                result = future.result()
            except Exception as e:
                logger.error(f"Worker failed processing question: {e}")
                continue
            if result:
                if result["item_id"] in processed_ids:
                    continue

                dataset["question"].append(result["question"])
                dataset["answer"].append(result["answer"])
                if args.mode == "ans":
                    dataset["ground_truth"].append(result["ground_truth"])
                    dataset["citations"].append(result["citations"])
                    dataset["type"].append(result["type"])

                processed_count += 1
                processed_ids.add(result["item_id"])
                processed_since_checkpoint += 1

                if processed_since_checkpoint >= args.checkpoint_every:
                    save_checkpoint(
                        checkpoint_file,
                        dataset,
                        processed_ids,
                        start_time,
                        total_questions,
                    )
                    logger.info(
                        "Checkpoint saved (%d/%d complete).",
                        len(processed_ids),
                        total_questions,
                    )
                    processed_since_checkpoint = 0

    execution_time = time.time() - start_time
    logger.info(f"TIME TAKEN >>>>>>>>>>> {execution_time} <<<<<<<<<<<")
    
    if args.mode == "ans":
        dataset['time'] = execution_time
    
    save_checkpoint(
        checkpoint_file,
        dataset,
        processed_ids,
        start_time,
        total_questions,
    )
    with open(output_file, 'wb') as f:
        pickle.dump(dataset, f)
