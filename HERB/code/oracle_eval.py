import os
import json
import argparse
from pathlib import Path
from tqdm import tqdm
import pickle
import time
import logging
from utils import get_gpt4_response


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def build_context(product_data, content_map, citations, employee_data, customers_data):
    context = []
    if product_data.get('team'):
        role_to_employees = {}
        for emp_id in product_data['team']:
            emp = employee_data.get(emp_id)
            if emp['role'] not in role_to_employees:
                role_to_employees[emp['role']] = []
            role_to_employees[emp['role']].append(f"{emp_id} ({emp['name']})")
        team_str = "TEAM STRUCTURE:\n"
        for role, employees in role_to_employees.items():
            team_str += f"{role}: {', '.join(employees)}\n"
        context.append(team_str)

    if product_data.get('customers'):
        customer_str = "CUSTOMERS:\n"
        for cid in product_data['customers']:
            customer_str += f"{cid}: {customers_data[cid]}\n"
        context.append(customer_str)

    for cid in citations:
        content = content_map[cid]
        context.append(content)
        
    return '\n\n'.join(context)

def evaluate_product(product_json_path, model_func, employee_data, customers_data):
    product_name = Path(product_json_path).stem
    product_data = load_json(product_json_path)
    results = {
        "product": product_name,
        "answer": [],
        "ground_truth": [],
        "question": [],
        "citations": [],
        "type": []
    }

    content_map = {}

    for utter in product_data['slack']:
        message_id = utter['Message']['User']['utterranceID']
        sender = utter['Message']['User']['userId']
        message = utter['Message']['User']['text']
        utterance_content = f"{sender}: {message}"
        content_map[message_id] = utterance_content

    for d in product_data['documents']:
        doc_id = d['id']
        doc_content = f"Doc ID: {doc_id}\nLink: {d['document_link']}\n{d['date']}\nAuthor: {d['author']}\n\n{d['type']}\n{d['content']}"
        content_map[doc_id] = doc_content

    for d in product_data["meeting_transcripts"]:
        meeting_id = d['id']
        transcript = f"Meeting ID: {meeting_id}\n{d['date']}\nParticipants: {d['participants']}\n\n{d['transcript']}"
        content_map[meeting_id] = transcript

    for d in product_data["meeting_chats"]:
        chat_id = d['id']
        chat_content = f"Meeting ID: {chat_id}\n\nChats:\n{d['text']}"
        content_map[chat_id] = chat_content
                
    for url in product_data["urls"]:
        url_id = url['id']
        url_content = f"URL: {url['link']}\n\nDescription: {url['description']}"
        content_map[url_id] = url_content
        
    for pr in product_data["prs"]:
        pr_id = pr['id']
        summary_str = f"Title: {pr['title']}\nAuthor: {pr['user']['login']}\nCreated At: {pr['created_at']}\nState: {pr['state']}\nMergeable: {pr['mergeable']}\nMerged: {pr['merged']}\nLink: {pr['link']}\nSummary: {pr['summary']}\n\nReviews:\n"
        for review in pr['reviews']:
            summary_str += f"- {review['state']} by {review['user']['login']} at {review['submitted_at']}: {review['comment']}\n"
        content_map[pr_id] = summary_str

    for qa in tqdm(product_data.get('answerable_questions', []), desc=f"{product_name}"):
        question = qa['question']
        ground_truth = qa['ground_truth']
        citations = qa['citations']
        context = build_context(product_data, content_map, citations, employee_data, customers_data)
        prompt = f"""You are a helpful AI assistant. Use the following product context to answer the given multi-hop question. Use reasoning to find answer in the context. If the answer cannot be found in the context, say \"I cannot answer this question based on the provided context.
        
Product Context:
{context}
        
Question:
{question}
        
Answer:
"""
        messages = [{'role': 'user', 'content': prompt}]

        answer = model_func(messages, "gpt-4o")
        results["answer"].append(answer)
        results["ground_truth"].append(ground_truth)
        results["question"].append(question)
        results["citations"].append(citations)
        results["type"].append(qa["type"])
    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data_dir', type=str, default="../data/products", help="Directory with product JSON files")
    parser.add_argument('--output_dir', type=str, default="output", help="Where to save results")
    args = parser.parse_args()

    customers_data = {}

    with open('../data/metadata/employee.json', 'r') as f:
        employee_data = json.load(f)
    with open('../data/metadata/customers_data.json', 'r') as f:
        data = json.load(f)
        for customer in data:
            customers_data[customer['id']] = customer["company"]

    os.makedirs(args.output_dir, exist_ok=True)
    product_files = [str(f) for f in Path(args.data_dir).glob("*.json")]

    all_results = {
        "answer": [],
        "ground_truth": [],
        "question": [],
        "citations": [],
        "type": [],
        "product": []
    }
    for product_json in product_files:
        logger.info(f"Evaluating {product_json}")
        results = evaluate_product(product_json, get_gpt4_response, employee_data, customers_data)
        for k in all_results:
            if k in results:
                all_results[k].extend(results[k])
        all_results["product"].extend([results["product"]]*len(results["question"]))
    # Save as pickle
    output_path = os.path.join(args.output_dir, "oracle_eval_results.pk")
    with open(output_path, 'wb') as f:
        pickle.dump(all_results, f)
    logger.info(f"Saved results to {output_path}")

if __name__ == "__main__":
    main() 