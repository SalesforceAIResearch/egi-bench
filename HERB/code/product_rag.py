from react import MyRAG
import json
import os
import csv
import pickle
from metadata_search_functions import finish_agent
from llama_index.core import QueryBundle
from react import CONTEXT_AGENT
from llama_index.core.agent import ReActAgent
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import uuid
import glob
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def process_question(args):
    question, myrag, data, num_attempts, mode = args
    agent = ReActAgent.from_tools(
        myrag.tools,
        llm=myrag.llm,
        # verbose=True,
        max_iterations=10,
        contexts=CONTEXT_AGENT,
    )
    
    if mode == "ans":
        response = {
            "question": question,
            "answer": None,
            "ground_truth": data["ground_truth"],
            "citations": data["citations"],
            "type": data["type"]
        }
    else: 
        response = {
            "question": question,
            "answer": None
        }
    
    for attempt in range(num_attempts):
        try:
            logger.info(f">>>>>>>>> QUESTION >>>>>>>>>>> {question}")
            logger.info(f">>>>>>>>> ATTEMPT >>>>>>>>>>> {attempt}")
            answer = agent.chat(question)
            logger.info(f'>>>>>>>>> ANSWER >>>>>>>>>>> {answer}')
            done = finish_agent(question, answer)
            if done:
                response["answer"] = answer
                return response
            
            # Reset agent if attempt failed
            agent = ReActAgent.from_tools(
                myrag.tools,
                llm=myrag.llm,
                # verbose=True,
                max_iterations=10,
                contexts=CONTEXT_AGENT,
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
            response["answer"] = fallback_answer
    except Exception as e:
        logger.exception(
            "Error processing question with fallback agent (%s): %r",
            type(e).__name__,
            e,
        )
    return response



def process_product(product_file, args):
    """Process a single product file and return results"""
    product_name = Path(product_file).stem
    logger.info(f"Processing product: {product_name}")
    
    product_save_index_path = f"index/{args.embedding_model_name}/{product_name}"
    product_load_index_path = product_save_index_path if args.reuse_index else None
    
    try:
        myrag = MyRAG(
            product_data=product_file,
            load_index_path=product_load_index_path,
            save_index_path=product_save_index_path,
            embedding_mode=args.embedding_mode,
            embedding_model_name=args.embedding_model_name,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            model_name=args.model_name,
            llm_provider=args.llm_provider
        )
    except Exception as e:
        print(f"Error initializing RAG for product {product_name}: {e}")
        return None
    
    with open(product_file, 'r') as f:
        product_data = json.load(f)
    
    qa_dataset = []
    if args.mode == "unans" and "unanswerable_questions" in product_data:
        qa_dataset.extend([{"question": q} for q in product_data["unanswerable_questions"]])
    elif args.mode == "ans" and "answerable_questions" in product_data:
        qa_dataset.extend(product_data["answerable_questions"])
    
    if not qa_dataset:
        print(f"No questions found for product {product_name} in mode {args.mode}")
        return None
    
    logger.info(f"Found {len(qa_dataset)} questions for product {product_name}")
    
    if args.mode == "ans":
        dataset = {
            "product": product_name,
            "answer": [],
            "ground_truth": [],
            "question": [],
            "citations": [],
            "type": []
        }
    else:  # unans mode
        dataset = {
            "product": product_name,
            "answer": [],
            "question": []
        }

    start_time = time.time()
    processed_count = 0
    
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        tasks = [(data["question"], myrag, data, args.num_attempts, args.mode) for data in qa_dataset]
        
        futures = [executor.submit(process_question, task) for task in tasks]
        
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"Processing {product_name}"):
            result = future.result()
            if result:
                dataset["question"].append(result["question"])
                dataset["answer"].append(result["answer"])
                if args.mode == "ans":
                    dataset["ground_truth"].append(result["ground_truth"])
                    dataset["citations"].append(result["citations"])
                    dataset["type"].append(result["type"])
                
                processed_count += 1
    
    execution_time = time.time() - start_time
    logger.info(f"TIME TAKEN FOR {product_name} >>>>>>>>>>> {execution_time} <<<<<<<<<<<<<")
    
    if args.mode == "ans":
        dataset['time'] = execution_time
    
    logger.info(f"Successfully completed processing for {product_name}")
    
    return dataset


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
    )
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
    
    args = parser.parse_args()

    os.makedirs("output", exist_ok=True)
    product_dir = "../data/products"

    product_files = glob.glob(os.path.join(product_dir, "*.json"))
    
    logger.info(f"Processing {len(product_files)} product files:")
    for pf in product_files:
        logger.info(f"  - {Path(pf).stem}")
    
    if args.mode == "ans":
        combined_results = {
            "answer": [],
            "ground_truth": [],
            "question": [],
            "citations": [],
            "type": []
        }
    else:
        combined_results = {
            "answer": [],
            "question": []
        }
    
    overall_start_time = time.time()
    products_processed = 0
    
    for product_file in product_files:
        try:
            result = process_product(product_file, args)
            if result:
                combined_results["answer"].extend(result["answer"])
                combined_results["question"].extend(result["question"])
                if args.mode == "ans":
                    combined_results["ground_truth"].extend(result["ground_truth"])
                    combined_results["citations"].extend(result["citations"])
                    combined_results["type"].extend(result["type"])
                products_processed += 1
        except Exception as e:
            print(f"Error processing product file {product_file}: {e}")
            continue
    
    overall_execution_time = time.time() - overall_start_time
    combined_results["time"] = overall_execution_time
    
    logger.info(f"OVERALL PROCESSING COMPLETED")
    logger.info(f"Total time: {overall_execution_time:.2f} seconds")
    logger.info(f"Products processed: {products_processed}")
    
    output_file = f'output/product_rag-{args.embedding_model_name}-{args.model_name.replace("/", "_")}-{args.num_attempts}-{args.mode}.pk'
    with open(output_file, 'wb') as f:
        pickle.dump(combined_results, f)
    
    logger.info(f"Final results saved to {output_file}")
