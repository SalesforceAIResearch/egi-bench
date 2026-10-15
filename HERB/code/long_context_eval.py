import os
import json
import argparse
from pathlib import Path
from tqdm import tqdm
import pickle
import time
import re
from collections import defaultdict
from datetime import datetime
import logging
from utils import get_gpt4_response


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def build_long_context(product_data, employee_data, customers_data):
    sections = []
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
        sections.append(team_str)
    if product_data.get('customers'):
        customer_str = "CUSTOMERS:\n"
        for cid in product_data['customers']:
            customer_str += f"{cid}: {customers_data[cid]}\n"
        sections.append(customer_str)
        
    if product_data.get('slack'):
        channels = defaultdict(list)
        for slack_item in product_data['slack']:
            channel_id = slack_item['Channel']['channelID']
            channel_name = slack_item['Channel']['name']
            message = slack_item['Message']
            
            timestamp = datetime.fromisoformat(message['User']['timestamp'])
            
            channels[channel_id].append({
                'channel_name': channel_name,
                'timestamp': timestamp,
                'user_id': message['User']['userId'],
                'text': message['User']['text'],
                'utterance_id': message['User']['utterranceID']
            })
        
        for channel_id in channels:
            channels[channel_id].sort(key=lambda x: x['timestamp'])
        
        slack_sections = []
        for channel_id, messages in channels.items():
            channel_name = messages[0]['channel_name']  # All messages in channel have same name
            channel_messages = []
            for msg in messages:
                channel_messages.append(f"{msg['user_id']}: {msg['text']}")
            
            if channel_messages:
                slack_sections.append(f"Channel: {channel_name}\n" + "\n".join(channel_messages))
        
        if slack_sections:
            sections.append("SLACK CHANNELS\n\n" + "\n\n".join(slack_sections))
            
    if product_data.get('meeting_transcripts'):
        transcripts = []
        for d in product_data['meeting_transcripts']:
            transcripts.append(f"Meeting ID: {d['id']}\n{d['date']}\nParticipants: {d['participants']}\n\n{d['transcript']}")
        if transcripts:
            sections.append("MEETING TRANSCRIPTS\n" + "\n\n".join(transcripts))

    if product_data.get('meeting_chats'):
        chats = []
        for d in product_data['meeting_chats']:
            chats.append(f"Meeting ID: {d['id']}\nChats:\n{d['text']}")
        if chats:
            sections.append("MEETING CHATS\n" + "\n\n".join(chats))
            
    if product_data.get('documents'):
        docs = []
        for d in product_data['documents']:
            docs.append(f"Doc ID: {d['id']}\nLink: {d['document_link']}\n{d['date']}\nAuthor: {d['author']}\n\n{d['type']}\n{d['content']}")
        if docs:
            sections.append("DOCUMENTS\n" + "\n\n".join(docs))
            
    if product_data.get('urls'):
        urls = []
        for url in product_data['urls']:
            urls.append(f"URL: {url['link']}\n\nDescription: {url['description']}")
        if urls:
            sections.append("URLs\n" + "\n\n".join(urls))
            
    if product_data.get('prs'):
        prs = []
        for pr in product_data['prs']:
            summary_str = f"Title: {pr['title']}\nAuthor: {pr['user']['login']}\nCreated At: {pr['created_at']}\nState: {pr['state']}\nMergeable: {pr['mergeable']}\nMerged: {pr['merged']}\nLink: {pr['link']}\nSummary: {pr['summary']}\n\nReviews:\n"
            for review in pr['reviews']:
                summary_str += f"- {review['state']} by {review['user']['login']} at {review['submitted_at']}: {review['comment']}\n"
            prs.append(summary_str)
        if prs:
            sections.append("PULL REQUESTS\n" + "\n\n".join(prs))
    return '\n\n'.join(sections)


def evaluate_product_long_context(product_json_path, model_func, employee_data, customers_data, mode="ans"):
    product_name = Path(product_json_path).stem
    product_data = load_json(product_json_path)
    
    if mode == "ans":
        results = {
            "product": product_name,
            "answer": [],
            "ground_truth": [],
            "question": [],
            "citations": [],
            "type": []
        }
        questions_data = product_data.get('answerable_questions', [])
    else:  # unans mode
        results = {
            "product": product_name,
            "answer": [],
            "question": []
        }
        questions_data = [{"question": q} for q in product_data.get('unanswerable_questions', [])]

    for idx, qa in tqdm(enumerate(questions_data), desc=f"{product_name}"):
        question = qa['question']
        context = build_long_context(product_data, employee_data, customers_data)
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
        results["question"].append(question)
        
        if mode == "ans":
            results["ground_truth"].append(qa['ground_truth'])
            results["citations"].append(qa['citations'])
            results["type"].append(qa["type"])
    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data_dir', type=str, default="../data/products", help="Directory with product JSON files")
    parser.add_argument('--output_dir', type=str, default="output", help="Where to save results")
    parser.add_argument(
        "--mode",
        choices=["ans", "unans"],
        default="ans",
        help="Mode to run in: 'ans' for answerable questions, 'unans' for unanswerable questions",
    )
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
    
    if args.mode == "ans":
        all_results = {
            "answer": [],
            "ground_truth": [],
            "question": [],
            "citations": [],
            "type": [],
            "product": []
        }
    else:  # unans mode
        all_results = {
            "answer": [],
            "question": [],
            "product": []
        }
    
    for product_json in product_files:
        logger.info(f"Evaluating {product_json}")
        results = evaluate_product_long_context(product_json, get_gpt4_response, employee_data, customers_data, args.mode)
        for k in all_results:
            if k in results:
                all_results[k].extend(results[k])
        all_results["product"].extend([results["product"]]*len(results["question"]))
    
    output_path = os.path.join(args.output_dir, f"long_context_eval_gpt_results_{args.mode}.pk")
    with open(output_path, 'wb') as f:
        pickle.dump(all_results, f)
    logger.info(f"Saved results to {output_path}")

if __name__ == "__main__":
    main()