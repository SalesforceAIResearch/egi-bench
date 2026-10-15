#!/usr/bin/env python3
"""
Wrapper script to run HERB evaluation via the LiteLLM proxy.
Sets up the environment to route all OpenAI API calls through the local proxy.
"""

import os
import sys

# Configure to use the LiteLLM proxy
os.environ['OPENAI_API_KEY'] = 'dummy'  # Required but not used by proxy
os.environ['OPENAI_API_BASE'] = 'http://localhost:8008/v1'

# Import after setting environment
from openai import OpenAI

# Monkey patch the OpenAI client to use the LiteLLM proxy by default
import llama_index.llms.openai as llm_openai
import llama_index.embeddings.openai as emb_openai

original_openai_init = llm_openai.OpenAI.__init__
original_embedding_init = emb_openai.OpenAIEmbedding.__init__

def patched_openai_init(self, *args, **kwargs):
    if 'api_base' not in kwargs and 'base_url' not in kwargs:
        kwargs['api_base'] = 'http://localhost:8008/v1'
    if 'api_key' not in kwargs:
        kwargs['api_key'] = 'dummy'
    return original_openai_init(self, *args, **kwargs)

def patched_embedding_init(self, *args, **kwargs):
    if 'api_base' not in kwargs:
        kwargs['api_base'] = os.environ.get('OPENAI_BASE_URL', 'http://localhost:8008/v1')
    if 'api_key' not in kwargs:
        kwargs['api_key'] = os.environ.get('OPENAI_API_KEY', 'dummy')
    return original_embedding_init(self, *args, **kwargs)

llm_openai.OpenAI.__init__ = patched_openai_init
emb_openai.OpenAIEmbedding.__init__ = patched_embedding_init

# Now import and run the actual evaluation
sys.path.insert(0, 'code')
import rag

if __name__ == "__main__":
    # The rag module will use sys.argv, so we're good
    pass
