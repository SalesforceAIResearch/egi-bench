# Benchmarking Deep Search over Heterogeneous Enterprise Data

**Paper:** [Arxiv Link](https://arxiv.org/abs/2506.23139)  
**Dataset:** [Huggingface Link](https://huggingface.co/datasets/Salesforce/HERB)

We present a new benchmark for evaluating Deep Search--a realistic and complex form of retrieval-augmented generation (RAG) that requires source-aware, multi-hop reasoning over diverse, sparsed, but related sources. These include documents, meeting transcripts, Slack messages, GitHub, and URLs, which vary in structure and often contain human-to-human interactions. We build it using a synthetic data pipeline that simulates business workflows across product planning, development, and support stages, generating interconnected content with realistic noise and multi-hop questions with guaranteed ground-truth answers. We release our benchmark with both answerable and unanswerable queries, and retrieval pool of 39,190 enterprise artifacts, enabling fine-grained evaluation of long-context LLM and RAG systems. Our experiments reveal that even the best-performing agentic RAG methods achieve an average performance score of 32.96 on our benchmark. With further analysis, we highlight retrieval as the main bottleneck: existing methods struggle to conduct deep searches and retrieve all necessary evidence. Consequently, they often reason over partial context, leading to significant performance degradation.

## Running via egi-bench (recommended)

HERB is wired into the [EGI-Bench](../README.md) suite. From the repository
root, after [`egi-bench setup`](../README.md#5-install-benchmark-environments)
provisions `HERB/.venv` and the [local LiteLLM proxy is running](../README.md#4-start-the-local-litellm-proxy):

```bash
# Quick mode: capped to 80 questions per ans/unans split
egi-bench run --model gpt-4o-mini --mode quick --benchmarks herb

# Deep mode: full ans + unans splits
egi-bench run --model gpt-4o-mini --mode deep --benchmarks herb
```

Embedding defaults (`huggingface` + `BAAI/bge-small-en-v1.5`), worker count,
and per-mode question caps live in
[`benchmark_config.yaml`](../benchmark_config.yaml) under `benchmarks.herb`.

For development of a single split, see
[`docs/benchmarks.md`](../docs/benchmarks.md#herb) and the standalone
instructions below.

## Standalone Setup

Use these instructions only when developing or debugging HERB outside the
unified runner. `egi-bench setup` already performs the `uv venv` /
`uv pip install -r requirements.txt` steps for you.

### 1. Create Virtual Environment

```bash
cd HERB
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 2. Install Dependencies

```bash
uv pip install -r requirements.txt
```

### 3. Configure LLM Access

**Option A: Use the local LiteLLM proxy (matches the egi-bench setup)**

Ensure the LiteLLM proxy service is running (see the [parent README](../README.md#4-start-the-local-litellm-proxy)):

```bash
# In a separate terminal, from the repository root
cd litellm_proxy
bash start_server.sh
```

The evaluation scripts will automatically use the proxy when configured properly.

**Option B: Direct API Keys**

Set your API key for OpenAI, Together AI, or Vertex AI:

```bash
export OPENAI_API_KEY='yourkey'
# OR
export TOGETHER_API_KEY='yourkey'
# OR set up Vertex AI: https://cloud.google.com/vertex-ai/generative-ai/docs/start/quickstart
```

### 4. Test Setup

Run the simple test to verify everything is working:

```bash
python test_simple.py
```

## Usage

Navigate to the code directory:

```bash
cd code
```

### 1. RAG over all data

```bash
python rag.py --mode ans    # Answerable Evaluation
python rag.py --mode unans  # Unanswerable Evaluation
```

**Recommended LiteLLM-proxy invocation (matches what `egi-bench run` issues internally):**

```bash
python rag.py \
  --mode ans \
  --model_name gpt-4.1-nano \
  --api_base http://localhost:8008/v1 \
  --embedding_mode huggingface \
  --embedding_model_name BAAI/bge-small-en-v1.5 \
  --reuse_index
```

**Operational flags for long runs:**

- `--max_questions N`: limit the number of questions (useful for smoke tests).
- `--checkpoint_every N`: save progress every N completed questions (default: 25).
- `--resume_checkpoint`: resume from `output/*.checkpoint` (or fallback to existing `output/*.pk`) and skip already completed questions.

Example quick validation run:

```bash
python rag.py \
  --mode ans \
  --model_name gpt-4.1-nano \
  --api_base http://localhost:8008/v1 \
  --embedding_mode huggingface \
  --embedding_model_name BAAI/bge-small-en-v1.5 \
  --reuse_index \
  --max_questions 50 \
  --checkpoint_every 10
```

Resume later with the same command plus:

```bash
--resume_checkpoint
```

### 2. Product-Specific RAG

```bash
python product_rag.py --mode ans    # Answerable Evaluation
python product_rag.py --mode unans  # Unanswerable Evaluation
```

### 3. Long Context Setting

```bash
python long_context_eval.py --mode ans    # Answerable Evaluation
python long_context_eval.py --mode unans  # Unanswerable Evaluation
```

### 4. Oracle Setting

```bash
python oracle_eval.py   # Answerable Evaluation
```

### 5. Evaluation

```bash
python evaluate.py --output_file {output_file_name}
```

## Ethical Considerations

HERB was generated using GPT-4o and should not be used to develop models that compete with OpenAI.

This release is for research purposes only in support of an academic paper. Our models, datasets, and code are not specifically designed or evaluated for all downstream purposes. We strongly recommend users evaluate and address potential concerns related to accuracy, safety, and fairness before deploying this model. We encourage users to consider the common limitations of AI, comply with applicable laws, and leverage best practices when selecting use cases, particularly for high-risk scenarios where errors or misuse could significantly impact people's lives, rights, or safety. For further guidance on use cases, refer to our AUP and AI AUP.

## Citation

```bibtex
@article{choubey2025benchmarkingdeepsearchheterogeneous,
    title={Benchmarking Deep Search over Heterogeneous Enterprise Data},
    author={Prafulla Kumar Choubey and Xiangyu Peng and Shilpa Bhagavath and Kung-Hsiang Huang and Caiming Xiong and Chien-Sheng Wu},
    year={2025},
    eprint={2506.23139},
    archivePrefix={arXiv},
    primaryClass={cs.CL},
    url={https://arxiv.org/abs/2506.23139}
}
```
