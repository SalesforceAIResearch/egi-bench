#!/usr/bin/env python3
"""
Analyze PersonaBench evaluation results
"""
import argparse
import json
import sys
from collections import defaultdict

def normalize_answer(answer):
    """Normalize answer for comparison"""
    if isinstance(answer, (int, float)):
        return str(answer).lower().strip()
    elif isinstance(answer, list):
        return [str(a).lower().strip() for a in answer]
    return str(answer).lower().strip()

def check_correctness(prediction, answer):
    """Check if prediction matches answer"""
    pred_norm = normalize_answer(prediction)
    ans_norm = normalize_answer(answer)

    if isinstance(ans_norm, list):
        # Check if prediction contains any of the acceptable answers
        for acceptable in ans_norm:
            if acceptable in pred_norm or pred_norm in acceptable:
                return True
        return False
    else:
        # Direct comparison
        return ans_norm in pred_norm or pred_norm in ans_norm

def analyze_retrieval(result):
    """Check if ground truth segments were retrieved"""
    retrieved = set(result['retrieved_segment_ids'])
    ground_truth = set()
    for segments in result['ground_truth_segment_ids'].values():
        ground_truth.update(segments)

    if not ground_truth:
        return None

    retrieved_gt = retrieved.intersection(ground_truth)
    return len(retrieved_gt) > 0

def main():
    parser = argparse.ArgumentParser(description='Analyze PersonaBench evaluation results')
    parser.add_argument(
        '--results-file',
        default='logs/eval_data_v1/results_all_community_chunk_5/result_noise_0.0.json',
        help='Path to results JSON file',
    )
    args = parser.parse_args()
    results_file = args.results_file

    with open(results_file, 'r') as f:
        data = json.load(f)

    print("=" * 80)
    print("PersonaBench Results Analysis - gpt-5-nano + all-MiniLM-L6-v2")
    print("=" * 80)
    print()

    for model_result in data:
        model_name = model_result['Model']
        results = model_result['Results']

        print(f"Model: {model_name}")
        print(f"Total Questions: {len(results)}")
        print()

        # Overall accuracy
        correct = 0
        retrieval_success = 0
        retrieval_total = 0

        # By type
        by_type = defaultdict(lambda: {'correct': 0, 'total': 0})
        by_difficulty = defaultdict(lambda: {'correct': 0, 'total': 0})

        # Track errors
        errors = []

        for result in results:
            is_correct = check_correctness(result['prediction'], result['answer'])
            if is_correct:
                correct += 1
            else:
                errors.append({
                    'question': result['question'],
                    'answer': result['answer'],
                    'prediction': result['prediction'],
                    'type': result['type'],
                    'difficulty': result['difficulty']
                })

            # By type
            q_type = result['type']
            by_type[q_type]['total'] += 1
            if is_correct:
                by_type[q_type]['correct'] += 1

            # By difficulty
            difficulty = result['difficulty']
            by_difficulty[difficulty]['total'] += 1
            if is_correct:
                by_difficulty[difficulty]['correct'] += 1

            # Retrieval success
            ret_success = analyze_retrieval(result)
            if ret_success is not None:
                retrieval_total += 1
                if ret_success:
                    retrieval_success += 1

        # Print overall stats
        accuracy = (correct / len(results)) * 100
        print(f"Overall Accuracy: {correct}/{len(results)} ({accuracy:.1f}%)")
        print()

        # Retrieval stats
        if retrieval_total > 0:
            retrieval_rate = (retrieval_success / retrieval_total) * 100
            print(f"Retrieval Success Rate: {retrieval_success}/{retrieval_total} ({retrieval_rate:.1f}%)")
            print("(% of questions where at least one ground-truth segment was retrieved)")
            print()

        # By question type
        print("Performance by Question Type:")
        print("-" * 60)
        for q_type in sorted(by_type.keys()):
            stats = by_type[q_type]
            acc = (stats['correct'] / stats['total']) * 100
            print(f"  {q_type:30s}: {stats['correct']:2d}/{stats['total']:2d} ({acc:5.1f}%)")
        print()

        # By difficulty
        print("Performance by Difficulty:")
        print("-" * 60)
        for difficulty in sorted(by_difficulty.keys()):
            stats = by_difficulty[difficulty]
            acc = (stats['correct'] / stats['total']) * 100
            print(f"  {difficulty:10s}: {stats['correct']:2d}/{stats['total']:2d} ({acc:5.1f}%)")
        print()

        # Sample errors
        if errors:
            print(f"Sample Errors ({min(10, len(errors))} of {len(errors)}):")
            print("-" * 80)
            for i, error in enumerate(errors[:10]):
                print(f"\n{i+1}. Question: {error['question']}")
                print(f"   Expected: {error['answer']}")
                print(f"   Predicted: {error['prediction']}")
                print(f"   Type: {error['type']} | Difficulty: {error['difficulty']}")

        print()
        print("=" * 80)

if __name__ == "__main__":
    main()
