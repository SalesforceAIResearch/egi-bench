#!/usr/bin/env python3
"""
Simple test script for HERB evaluation via the LiteLLM proxy.
Tests if the basic setup works with minimal data.
"""

import os
import json
from openai import OpenAI

# Configure to use the LiteLLM proxy
client = OpenAI(
    base_url="http://localhost:8008/v1",
    api_key="dummy"
)

def test_gateway():
    """Test if the LiteLLM proxy is accessible"""
    print("Testing LiteLLM proxy connection...")
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello, respond with 'OK'"}],
            max_tokens=10
        )
        print(f"✓ Gateway working: {response.choices[0].message.content}")
        return True
    except Exception as e:
        print(f"✗ Gateway error: {e}")
        return False

def test_data_loading():
    """Test if HERB data can be loaded"""
    print("\nTesting data loading...")
    try:
        with open('data/products/ActionGenie.json', 'r') as f:
            data = json.load(f)

        answerable = len(data.get('answerable_questions', []))
        unanswerable = len(data.get('unanswerable_questions', []))

        print(f"✓ Loaded ActionGenie data:")
        print(f"  - {answerable} answerable questions")
        print(f"  - {unanswerable} unanswerable questions")

        if answerable > 0:
            sample = data['answerable_questions'][0]
            print(f"\n  Sample question: {sample['question'][:100]}...")

        return True
    except Exception as e:
        print(f"✗ Data loading error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("HERB Simple Test")
    print("=" * 60)

    gateway_ok = test_gateway()
    data_ok = test_data_loading()

    print("\n" + "=" * 60)
    if gateway_ok and data_ok:
        print("✓ All tests passed! HERB is ready to use.")
        print("\nNext steps:")
        print("  cd code")
        print("  python rag.py --mode ans --model_name gpt-4o-mini")
    else:
        print("✗ Some tests failed. Please check the errors above.")
    print("=" * 60)
