from llama_index.core import (
    VectorStoreIndex,
    load_index_from_storage,
)

from llama_index.llms.vertex import Vertex
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.retrievers import (
    BaseRetriever,
    VectorIndexRetriever
)

from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core import StorageContext
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.core.storage.index_store import SimpleIndexStore
from llama_index.core.vector_stores import SimpleVectorStore
from llama_index.core.node_parser import SentenceSplitter
import nest_asyncio
from typing import Literal

nest_asyncio.apply()
from llama_index.core import Settings

from llama_index.core.agent.workflow import ReActAgent
from llama_index.core.tools import RetrieverTool
from llama_index.llms.openai_like import OpenAILike
from metadata_search_functions import (
    role_id_search_tool,
    name_id_search_tool,
    company_id_search_tool,
    id_company_search_tool,
    id_name_search_tool,
    id_role_search_tool,
    pr_search_tool,
    url_search_tool
)
import json
from pathlib import Path
from llama_index.core import Document

from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.together import TogetherLLM
import os


CONTEXT_AGENT = """You are an intelligent assistant designed to answer questions about products using a variety of enterprise data sources.

You will have access to the following information:

* **Employee directory**: Names, employee IDs, and roles.
* **Slack conversations**: Messages exchanged across different channels, including timestamps, employee IDs, and document URLs.
* **Meeting records**: Natural language transcripts with timestamps, meeting IDs, and participant employee IDs.
* **Referenced documents**: Each includes the author's name and ID, timestamp, title, and full content.
* **GitHub pull request descriptions**: Summaries of PRs related to feature development or bug fixes across different products.
* **Web URL summaries**: Descriptions of content retrieved from external URLs.

Your goal is to retrieve and synthesize relevant information from conversations, meetings, documents, and other sources to answer the given product-related question.

To support this:

* **Unstructured search** uses semantic similarity to retrieve relevant Slack messages, documents, meeting transcripts and chats.
* **Structured search** enables precise extraction of metadata related to employees, customers, pull requests, and URLs.
"""

class EnsembleRetriever(BaseRetriever):
    def __init__(self, vector_retriever, bm25_retriever):
        self.vector_retriever = vector_retriever
        self.bm25_retriever = bm25_retriever
        super().__init__()

    def _retrieve(self, query, **kwargs):
        bm25_nodes = self.bm25_retriever.retrieve(query, **kwargs)
        vector_nodes = self.vector_retriever.retrieve(query, **kwargs)

        all_nodes = []
        node_ids = set()
        for n in bm25_nodes + vector_nodes:
            if n.node.node_id not in node_ids:
                all_nodes.append(n)
                node_ids.add(n.node.node_id)
        return all_nodes


class MyRAG:

    def __init__(
            self,
            product_data: str,
            load_index_path: str,
            save_index_path: str,
            similarity_top_k: int = 20,
            embedding_mode: Literal["openai", "huggingface"] = "openai",
            embedding_model_name: str = "text-embedding-3-large",
            chunk_size: int = 1024,
            chunk_overlap: int = 96,
            model_name: str = "gpt-4o",
            llm_provider: Literal["openai", "togetherai"] = "openai",
            api_base: str = None,
            context_window: int = 400000,
    ):
        self.product_data = product_data
        self.load_index_path = load_index_path
        self.save_index_path = save_index_path
        self.model_name = model_name

        if llm_provider == "openai":
            # Use ``OpenAILike`` for the OpenAI branch so HERB can run any
            # OpenAI-wire-compatible model — including newer / vendor-specific
            # variants (e.g. ``gpt-5.5`` exposed via the LiteLLM proxy) that are
            # not yet present in llama-index's hardcoded model registry.
            #
            # The stock ``llama_index.llms.openai.OpenAI`` class derives its
            # ``LLMMetadata.context_window`` by looking the model name up in a
            # static dict (``ALL_AVAILABLE_MODELS``) and raises
            # ``ValueError: Unknown model '<name>'`` for anything missing
            # there — even when the request would otherwise be routed cleanly
            # through ``api_base``. ``OpenAILike`` instead reads
            # ``context_window`` from the user, removing that coupling without
            # changing wire-protocol behavior.
            #
            # ``is_chat_model=True`` is also required: ``OpenAILike`` defaults
            # to ``False``, which routes calls to the legacy
            # ``POST /v1/completions`` endpoint. The local LiteLLM proxy only
            # implements ``/v1/chat/completions``, so the default would 404
            # every request before the ReAct loop runs.
            llm_kwargs = {
                "model": model_name,
                "temperature": 0.1,
                "context_window": context_window,
                "is_chat_model": True,
                "is_function_calling_model": True,
            }
            if api_base:
                llm_kwargs["api_base"] = api_base
                llm_kwargs["api_key"] = "dummy"  # Required but not used by gateway
            self.llm = OpenAILike(**llm_kwargs)
        elif llm_provider == "gemini":
            self.llm = Vertex(model=model_name, temperature=0.1, max_tokens=32000,
                              context_window=131000)  # Gemini(model=model_name, temperature=0.1)
        elif llm_provider == "togetherai":
            self.llm = TogetherLLM(
                model=model_name, temperature=0.1,  # deepseek-ai/DeepSeek-R1
                api_key=os.environ.get("TOGETHER_API_KEY")
            )
        else:
            raise ValueError(f"Invalid LLM provider: {llm_provider}")
        Settings.llm = self.llm

        if embedding_mode == "openai":
            embed_kwargs = {"model": embedding_model_name}
            if api_base:
                embed_kwargs["api_base"] = api_base
                embed_kwargs["api_key"] = "dummy"  # Required but not used by gateway
            self.embed_model = OpenAIEmbedding(**embed_kwargs)
        elif embedding_mode == "huggingface":
            self.embed_model = HuggingFaceEmbedding(model_name=embedding_model_name)
        else:
            raise ValueError(f"Invalid embedding mode: [{embedding_mode}], model: [{embedding_model_name}]")
        Settings.embed_model = self.embed_model

        Settings.chunk_size = chunk_size
        Settings.chunk_overlap = chunk_overlap

        self._setup_data_loaders()

        self.storage_contexts, self.vector_indexs, self.document_nodes = self.build_index()
        self.tools = self.define_tools(similarity_top_k=similarity_top_k)
        # llama-index 0.14 migration: ``contexts=`` was renamed to
        # ``system_prompt=``; ``max_iterations`` is now per-call on
        # ``.run(...)`` (see ``rag.py`` for the actually-invoked agent).
        self.agent = ReActAgent(
            tools=self.tools,
            llm=self.llm,
            system_prompt=CONTEXT_AGENT,
            # verbose=True,
        )

    def _setup_data_loaders(self) -> None:

        documents = []
        data_path = Path(self.product_data)
        
        if data_path.is_file():
            if data_path.suffix == '.json':
                product_files = [data_path]
            else:
                raise ValueError(f"File must be a JSON file, got: {data_path}")
        elif data_path.is_dir():
            product_files = list(data_path.glob("*.json"))
        else:
            raise ValueError(f"Path does not exist: {data_path}")
        
        for product_file in product_files:
            try:
                with open(product_file, 'r') as f:
                    product_data = json.load(f)
                
                product_name = product_file.stem
                
                if 'slack' in product_data:
                    for slack_msg in product_data['slack']:
                        message_id = slack_msg["Message"]["User"]['utterranceID']
                        channel_name = slack_msg['Channel']['name']
                        timestamp = slack_msg["Message"]["User"]['timestamp']
                        user_id = slack_msg["Message"]['User']['userId']
                        text = slack_msg["Message"]['User']['text']
                        content = f"Message ID: {message_id}\nChannel Name: {channel_name}\nTimestamp: {timestamp}\n\n{user_id}: {text}"
                        doc = Document(text=content)
                        documents.append(doc)
                
                if 'documents' in product_data:
                    for doc_data in product_data['documents']:
                        doc_id = doc_data['id']
                        doc_content = f"Doc ID: {doc_id}\nLink: {doc_data['document_link']}\n{doc_data['date']}\nAuthor: {doc_data['author']}\n\n{doc_data['type']}\n{doc_data['content']}"
                        doc = Document(text=doc_content)
                        documents.append(doc)
                
                if 'meeting_transcripts' in product_data:
                    for transcript_data in product_data['meeting_transcripts']:
                        meeting_id = transcript_data['id']
                        transcript = f"Meeting ID: {meeting_id}\n{transcript_data['date']}\nParticipants: {transcript_data['participants']}\n\n{transcript_data['transcript']}"
                        doc = Document(text=transcript)
                        documents.append(doc)
                
                if 'meeting_chats' in product_data:
                    for chat_data in product_data['meeting_chats']:
                        chat_id = chat_data['id']
                        chat_content = f"Meeting ID: {chat_id}\n\nChats:\n{chat_data['text']}"
                        doc = Document(text=chat_content)
                        documents.append(doc)
                            
            except Exception as e:
                print(f"Error processing {product_file}: {e}")
                continue
        
        print(f"Total documents loaded: {len(documents)}")
        self.all_data = documents

    def define_tools(self, similarity_top_k):
        self.build_engine(similarity_top_k=similarity_top_k)
        retrieval_tool = RetrieverTool.from_defaults(
            self.retriever,
            name="retrieve_all",
            description="This tool uses vector search to retrieve information from all available unstructured sources including messages, internal documents, meetings and meeting chats. The retrieved information will include relevant metadata and content based on the query."
        )

        return [
            retrieval_tool,
            role_id_search_tool,
            name_id_search_tool,
            company_id_search_tool,
            id_company_search_tool,
            id_name_search_tool,
            id_role_search_tool,
            pr_search_tool,
            url_search_tool
        ]

    def build_index(self):
        if self.load_index_path:
            try:
                return self._load_existing_index()
            except (json.JSONDecodeError, FileNotFoundError, ValueError) as exc:
                # Cached index is corrupt or partially written (e.g. previous
                # embedding run crashed after writing docstore/index_store but
                # before persisting default__vector_store.json — that file
                # ends up 0 bytes and `json.load(f)` raises here). Wipe the
                # bad cache and fall through to a fresh build instead of
                # bringing the whole eval down.
                bad_dir = self._corrupt_index_dir()
                print(
                    f">>>WARN: cached index at {self.load_index_path!r} is "
                    f"corrupt ({type(exc).__name__}: {exc}). Removing "
                    f"{bad_dir!r} and rebuilding from scratch.>>>",
                    flush=True,
                )
                self._discard_corrupt_index()
                # Fall through to the build-new path below.

        return self._build_new_index()

    def _build_new_index(self):
        print(">>>Gen NEW index>>>")
        parser = SentenceSplitter()

        all_nodes = parser.get_nodes_from_documents(self.all_data)

        storage_context = StorageContext.from_defaults(
            docstore=SimpleDocumentStore(),
            vector_store=SimpleVectorStore(),
            index_store=SimpleIndexStore(),
        )
        storage_context.docstore.add_documents(all_nodes)

        vector_index = VectorStoreIndex(
            all_nodes,
            storage_context=storage_context,
            embed_model=self.embed_model,
            show_progress=True,
        )

        persist_dir = f"{self.save_index_path}"
        storage_context.persist(persist_dir)

        return storage_context, vector_index, all_nodes

    def _load_existing_index(self):
        print(">>>Reuse OLD index>>>")

        # Pre-flight: detect the most common corruption mode (a 0-byte
        # default__vector_store.json from a half-finished previous run)
        # before llama_index raises a deep JSONDecodeError, so the warning
        # log is more actionable.
        index_dir = Path(self.load_index_path)
        if index_dir.is_dir():
            for required in ("default__vector_store.json", "docstore.json", "index_store.json"):
                candidate = index_dir / required
                if candidate.is_file() and candidate.stat().st_size == 0:
                    raise ValueError(
                        f"Cached index file {candidate} is empty (0 bytes); "
                        "previous embedding run probably crashed mid-write."
                    )

        storage_context = StorageContext.from_defaults(
            persist_dir=f"{self.load_index_path}"
        )

        nodes = list(storage_context.docstore.docs.values())

        vector_index = load_index_from_storage(storage_context)

        return storage_context, vector_index, nodes

    def _corrupt_index_dir(self) -> str:
        return str(Path(self.load_index_path).resolve())

    def _discard_corrupt_index(self) -> None:
        """Remove the corrupt cache and switch to the build-new path."""
        import shutil

        index_dir = Path(self.load_index_path)
        if index_dir.exists():
            try:
                shutil.rmtree(index_dir)
            except OSError as e:
                # If we can't delete it, just unset load_index_path so the
                # rebuild persists somewhere fresh; leaks the bad cache but
                # doesn't fail the eval.
                print(
                    f">>>WARN: could not remove corrupt index dir {index_dir!r}: {e}. "
                    "Build will overwrite it.>>>",
                    flush=True,
                )
        # Force the build-new path on subsequent calls (and skip the load
        # branch above).
        self.load_index_path = None

    def build_engine(self, similarity_top_k, template=None, idx=0):
        if not self.vector_indexs:
            raise ValueError("Vector index not found. Please ensure vector indices are built when using vector mode.")
        vector_retriever = VectorIndexRetriever(
            index=self.vector_indexs,
            similarity_top_k=similarity_top_k
        )
        bm25_retriever = BM25Retriever.from_defaults(
            nodes=self.document_nodes,
            similarity_top_k=similarity_top_k
        )
        self.retriever = EnsembleRetriever(vector_retriever, bm25_retriever)
        self.fallback_query_engine = RetrieverQueryEngine.from_args(retriever=self.retriever)

    def fallback_answer(self, question: str) -> str:
        return self.fallback_query_engine.query(question)

