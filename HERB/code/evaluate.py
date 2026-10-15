import json
from collections import defaultdict
import pickle
import argparse
import os
import re
import string
import sys
from utils import get_gpt4_response


def unanswerability_eval(question, answer):
    prompt = """Given a question and its corresponding answer, determine whether the answer provides sufficient information to fully or even partially respond to the question.

- Reply "Yes" if the answer directly addresses the question, either fully or partially, using information relevant to the question.
- Reply "No" if the answer does not address the question due to missing, vague, or insufficient information — even if it explicitly states that the information is not available.

Question: Which products were affected by the bug in March?
Answer:  The context does not provide the specific information required to determine the products.
Output: No

Question: Find all authors and reviewers of the PRD?
Answer: John authored the PRD
Output: Yes

Question: Find all authors and reviewers of the PRD?
Answer: John authored the PRD. Yuan and Jessica reviewed the PRD.
Output: Yes
"""
    prompt += (
        f'\n\nQuestion: {question}\n\nAnswer: {answer}\n\nRespond using the below json format:\n{{"done": "yes/no", "reason": "justification for the decision"}}'
    )
    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    verification = get_gpt4_response(messages, response_format="json")
    if verification["done"].lower() == "no":
        return False
    return True

def answer_to_prs(question, content):
    prompt = (
        "The following is a question and its answer. The answer may include reasoning and a final answer. Extract only the pull request links that directly answer the question—that is, the links that refer to the specific PRs being asked about."
        "\n#Instructions:\n"
        "- Ignore PR links mentioned in reasoning or intermediate steps."
        "- If the question asks which PRs were reverted, extract the original PRs that were reverted, not the PRs that reverted them."
        "- If no pull request links directly answer the question, {{'links': []}}."
        "\n\nQuestion: {question}"
        "\n\nAnswer: {content}"
        "\n\nRespond in json format: {{'links': ['list of links']}}"
    ).format(question=question, content=content)

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    links = get_gpt4_response(messages, response_format="json")
    return links['links']

def answer_to_urls(question, content):
    prompt = (
        "The following is a question and its answer. The answer may include reasoning and a final answer. Extract only the URLs that directly answer the question—ignore any links mentioned in the reasoning or intermediate steps. If no URLs are part of the final answer, return {{'links': []}}."
        "\n\nQuestion: {question}"
        "\n\nAnswer: {content}"
        "\n\nRespond in json format: {{'links': ['list of links']}}"
    ).format(question=question, content=content)

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    links = get_gpt4_response(messages, response_format="json")
    return links['links']


def answer_to_companies(question, content):
    prompt = (
        "The following is a question and its answer. The answer may include reasoning and a final answer. Extract only the company names that directly answer the question—ignore any names mentioned in the reasoning or intermediate steps. If no company names are part of the final answer, return {{'names': []}}."
        "\n\nQuestion: {question}"
        "\n\nAnswer: {content}"
        "\n\nRespond in JSON format: {{'names': ['list of company names']}}"
    ).format(question=question, content=content)

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    names = get_gpt4_response(messages, response_format="json")
    return names['names']


def answer_to_employee_ids(question, content):
    prompt = (
        "The following is a question and its answer. The answer may include reasoning and a final answer. Extract only the employee IDs that directly answer the question—ignore any IDs mentioned in the reasoning or intermediate steps. If no employee IDs are part of the final answer, return {{'ids': []}}."
        "\n\nQuestion: {question}"
        "\n\nAnswer: {content}"
        "\n\nRespond in json format: {{'ids': ['list of employee IDs']}}"
    ).format(question=question, content=content)

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    ids = get_gpt4_response(messages, response_format="json")

    if ids:
        return ids['ids']
    return []


def answer_likert_score(question, reference, candidate):
    prompt = (
        "You are an expert evaluator. Given a question, a reference answer, "
        "and a candidate answer, your task is to evaluate how well the candidate "
        "answer aligns with the reference.\n\nFor your evaluation:"
        "\nFocus on accuracy, completeness, and relevance."
        "\nIf the candidate includes extra information, check if it's correct and appropriate."
        "\nIf it omits key points from the reference, mention that."
        "\nQuestion: {question}\nReference Answer: {reference}\nCandidate Answer: {candidate}"
        "\nRespond in json format: {{'score': 'Your overall rating between 0-100', "
        "'reason': 'a brief justification'}}'.").format(question=question, reference=reference, candidate=candidate)

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    score = get_gpt4_response(messages, response_format="json")
    return score['score']


def normalize(answer: str) -> str:
    def remove_articles(text):
        return re.sub(r"\b(a|an|the)\b", " ", text)
    def white_space_fix(text):
        return " ".join(text.split())
    def remove_punc(text):
        exclude = set(string.punctuation)
        return "".join(ch for ch in text if ch not in exclude)
    def lower(text):
        return text.lower()
    return white_space_fix(remove_articles(remove_punc(lower(answer))))


def turn_sample_lst2dataset(data_samples):
    samples_lst = []
    for idx in range(len(data_samples["question"])):
        answer = data_samples["answer"][idx]
        answer_text = "I don't know." if answer is None else (answer.response if not isinstance(answer, str) else answer)
        if "</think>" in answer_text:
            answer_text = answer_text.split("</think>")[-1].strip()
        samples_lst.append({"q": data_samples["question"][idx],
                            "r": data_samples['ground_truth'][idx],
                            "a": answer_text,
                            "t": data_samples["type"][idx]})
    return samples_lst


def f1_score_sets(y_true, y_pred):
    y_true_set = set([normalize(e) for e in y_true])
    y_pred_set = set([normalize(e) for e in y_pred])

    tp = len(y_true_set & y_pred_set)
    fp = len(y_pred_set - y_true_set)
    fn = len(y_true_set - y_pred_set)

    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
    return f1


def evaluate_answerable(dataset):
    dataset_eval = turn_sample_lst2dataset(dataset)
    dataset["gpt4-correctness"] = []
    scores = defaultdict(list)
    score = 0
    for d in dataset_eval:
        question = d["q"]
        answer = d["a"]
        reference = d["r"]
        type_map = d["t"]
        if type_map == "content":
            score = int(answer_likert_score(question, reference, answer))
            scores[type_map].append(score)
        else:  # company, content, person, url
            if type_map == "person":
                op = answer_to_employee_ids(question, answer)
            elif type_map == "url":
                op = answer_to_urls(question, answer)
            elif type_map == "pr":
                op = answer_to_prs(question, answer)
            elif type_map == "company":
                op = answer_to_companies(question, answer)
            else:
                print(type_map)
            score = f1_score_sets(op, reference)
            if type_map == "pr":
                type_map = "url"
            scores[type_map].append(score)
        dataset["gpt4-correctness"].append(score)
    
    avg_correctness = [c for c in dataset["gpt4-correctness"] if c >= 0]
    dataset["gpt4-correctness-avg"] = sum(avg_correctness) / len(avg_correctness)
    print(dataset["gpt4-correctness-avg"])

    averages = {key: sum(vals) / len(vals) if vals else 0 for key, vals in scores.items()}
    print(averages, len(dataset_eval), [len(vals) for key, vals in scores.items()])
    return dataset


def evaluate_unanswerable(dataset, test_size=10000):
    samples_lst = []
    inc = 0
    unanswered = 0
    for idx in range(len(dataset["question"])):
        answer = dataset["answer"][idx]
        if answer is None:
            unanswered += 1
            samples_lst.append({"q": dataset['question'][idx], "a": "unanswered", 's': 1})
        else:
            answer_text = answer.response if not isinstance(answer, str) else answer
            s = not unanswerability_eval(dataset['question'][idx], answer_text)
            if s:
                unanswered += 1
            samples_lst.append({"q": dataset['question'][idx], "a": answer_text, 's': int(s)})
        inc += 1
        if inc >= test_size-1:
            break
    print(f"Unanswered questions: {unanswered} ({unanswered/len(dataset['answer'])*100:.2f}%)")
    return samples_lst


def main():
    parser = argparse.ArgumentParser(description='Evaluate RAG results for both answerable and unanswerable questions')
    parser.add_argument('--output_file', type=str, required=True,
                      help='Path to the output file containing evaluation results (supports .json and .pk/.pkl files)')
    args = parser.parse_args()

    print(f"File {args.output_file}")
    if not os.path.exists(args.output_file):
        print(f"Error: File {args.output_file} does not exist", file=sys.stderr)
        sys.exit(1)

    is_unanswerable = "unans" in args.output_file.lower()

    file_ext = os.path.splitext(args.output_file)[1].lower()
    try:
        if file_ext in ['.pk', '.pkl']:
            with open(args.output_file, 'rb') as f:
                dataset = pickle.load(f)
        elif file_ext == '.json':
            with open(args.output_file, 'r') as f:
                dataset = json.load(f)
        else:
            print(
                f"Error: Unsupported file extension {file_ext}. Please use .json, .pk, or .pkl files.",
                file=sys.stderr,
            )
            sys.exit(1)
    except Exception as e:
        # Surface the failure as a non-zero exit so the orchestrator (run_all.py
        # / run_in_venv) can detect it. Previously this silently `return`ed,
        # leaving the pickle without `unanswerable_results` and producing
        # aggregate reports that look complete but are missing the M5 herb
        # contributor.
        print(f"Error loading file: {e}", file=sys.stderr)
        sys.exit(1)

    if is_unanswerable:
        print("Running unanswerable evaluation...")
        results = evaluate_unanswerable(dataset)
        dataset["unanswerable_results"] = results
    else:
        print("Running answerable evaluation...")
        dataset = evaluate_answerable(dataset)

    with open(args.output_file, 'wb') as f:
        pickle.dump(dataset, f)

if __name__ == "__main__":
    main() 