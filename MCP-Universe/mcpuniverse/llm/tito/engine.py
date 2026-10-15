"""
Direct vLLM Engine integration (no HTTP serve).

This module provides direct access to vLLM's AsyncLLMEngine for high-performance
inference without HTTP overhead. Similar to SkyRL-Agent's approach.

Usage:
    # With Ray (distributed training)
    from mcpuniverse.llm import AsyncVLLMEngine
    
    engine = AsyncVLLMEngine(
        model_path="meta-llama/Llama-3.1-8B-Instruct",
        tensor_parallel_size=1
    )
    await engine.init_engine()
    
    response, meta = await engine.generate(
        prompt_ids=[101, 2023, 2003, ...],
        sampling_params={"temperature": 0.7, "max_tokens": 512}
    )
    print(response)  # Generated text
    print(meta["output_tokens"])  # Token IDs
    print(meta["finish_reason"])  # stop, length, etc.
"""

from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import asyncio
import uuid

from loguru import logger

try:
    import ray
except ImportError:
    ray = None

try:
    from vllm import AsyncLLMEngine as _AsyncLLMEngine, SamplingParams
    from vllm.engine.arg_utils import AsyncEngineArgs
    from vllm.inputs import TokensPrompt
except ImportError:
    _AsyncLLMEngine = None
    SamplingParams = None
    AsyncEngineArgs = None
    TokensPrompt = None


@dataclass
class VLLMEngineConfig:
    """Configuration for vLLM engine."""
    model_path: str
    tensor_parallel_size: int = 1
    dtype: str = "auto"
    trust_remote_code: bool = True
    max_model_len: Optional[int] = None
    gpu_memory_utilization: float = 0.9
    enforce_eager: bool = False
    seed: int = 42
    # Additional vLLM engine args
    engine_args: Dict[str, Any] = field(default_factory=dict)


class AsyncVLLMEngine:
    """
    Direct vLLM AsyncLLMEngine wrapper (no HTTP serve).
    
    This provides:
    - Direct generate() with token IDs
    - Output token IDs and logprobs
    - No HTTP overhead
    - Compatible with VERL's distributed training
    
    Similar to SkyRL-Agent's SkyAgentAsyncvLLMServer.
    """

    def __init__(
        self,
        model_path: str,
        tensor_parallel_size: int = 1,
        dtype: str = "auto",
        trust_remote_code: bool = True,
        max_model_len: Optional[int] = None,
        gpu_memory_utilization: float = 0.9,
        **engine_args
    ):
        """
        Initialize the vLLM engine wrapper.

        Args:
            model_path: Path to the model (HuggingFace model ID or local path)
            tensor_parallel_size: Number of GPUs for tensor parallelism
            dtype: Data type for model weights
            trust_remote_code: Whether to trust remote code
            max_model_len: Maximum model context length
            gpu_memory_utilization: GPU memory utilization ratio
            **engine_args: Additional vLLM engine arguments
        """
        if _AsyncLLMEngine is None:
            raise ImportError(
                "vllm is required for AsyncVLLMEngine. "
                "Install with: pip install mcpuniverse[vllm]"
            )
        self.config = VLLMEngineConfig(
            model_path=model_path,
            tensor_parallel_size=tensor_parallel_size,
            dtype=dtype,
            trust_remote_code=trust_remote_code,
            max_model_len=max_model_len,
            gpu_memory_utilization=gpu_memory_utilization,
            engine_args=engine_args
        )

        self.engine = None
        self.tokenizer = None
        self.max_model_len = max_model_len
        self._initialized = False

    async def init_engine(self):
        """Initialize the vLLM AsyncLLMEngine."""
        if self._initialized:
            return

        engine_args = AsyncEngineArgs(
            model=self.config.model_path,
            tensor_parallel_size=self.config.tensor_parallel_size,
            dtype=self.config.dtype,
            trust_remote_code=self.config.trust_remote_code,
            max_model_len=self.config.max_model_len,
            gpu_memory_utilization=self.config.gpu_memory_utilization,
            enforce_eager=self.config.enforce_eager,
            seed=self.config.seed,
            **self.config.engine_args
        )

        self.engine = _AsyncLLMEngine.from_engine_args(engine_args)

        # Get max model length from engine if not specified
        if self.max_model_len is None:
            model_config = await self.engine.get_model_config()
            self.max_model_len = model_config.max_model_len

        self._initialized = True
        logger.info(f"[AsyncVLLMEngine] Initialized with max_model_len={self.max_model_len}")

    async def generate(
        self,
        prompt_ids: List[int],
        sampling_params: Dict[str, Any],
        request_id: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate text from token IDs.
        
        Args:
            prompt_ids: Input token IDs
            sampling_params: Sampling parameters dict
            request_id: Optional request ID for tracking
        
        Returns:
            Tuple of (response_text, meta_info)
            meta_info contains:
            - output_tokens: Generated token IDs
            - finish_reason: Why generation stopped
            - logprobs: Token log probabilities (if requested)
        """
        if not self._initialized:
            await self.init_engine()

        # Prepare sampling params
        sp = dict(sampling_params) if sampling_params else {}

        # Handle max_tokens
        if "max_tokens" not in sp or sp["max_tokens"] is None:
            sp["max_tokens"] = self.max_model_len - len(prompt_ids)
        else:
            sp["max_tokens"] = int(sp["max_tokens"])

        # Check for logprobs request
        return_logprobs = sp.pop("return_logprobs", False)
        if return_logprobs:
            sp["logprobs"] = sp.get("logprobs", 1)

        # Create vLLM SamplingParams
        vllm_params = SamplingParams(**sp)

        # Create prompt from token IDs
        prompt = TokensPrompt(prompt_token_ids=prompt_ids)

        # Generate request ID if not provided
        if request_id is None:
            request_id = str(uuid.uuid4())

        # Generate
        generator = self.engine.generate(
            prompt=prompt,
            sampling_params=vllm_params,
            request_id=request_id
        )

        # Get final response
        final_output = None
        async for output in generator:
            final_output = output

        assert final_output is not None, "No output from vLLM engine"

        # Extract results
        output_obj = final_output.outputs[0]
        response_text = output_obj.text
        output_tokens = list(output_obj.token_ids)
        finish_reason = output_obj.finish_reason

        # Extract logprobs if available
        logprobs = None
        if output_obj.logprobs:
            logprobs = [
                lp.logprob if lp else 0.0
                for lp in output_obj.logprobs
            ]

        meta_info = {
            "output_tokens": output_tokens,
            "finish_reason": finish_reason,
            "logprobs": logprobs,
            "prompt_tokens": len(prompt_ids),
            "completion_tokens": len(output_tokens),
        }

        return response_text, meta_info

    async def generate_batch(
        self,
        prompts: List[List[int]],
        sampling_params: Dict[str, Any],
        request_ids: Optional[List[str]] = None
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Generate for multiple prompts concurrently.
        
        Args:
            prompts: List of token ID sequences
            sampling_params: Shared sampling parameters
            request_ids: Optional list of request IDs
        
        Returns:
            List of (response_text, meta_info) tuples
        """
        if request_ids is None:
            request_ids = [str(uuid.uuid4()) for _ in prompts]

        tasks = [
            self.generate(prompt_ids, sampling_params, request_id)
            for prompt_ids, request_id in zip(prompts, request_ids)
        ]

        return await asyncio.gather(*tasks)

    async def get_tokenizer(self):
        """Get the tokenizer from the engine."""
        if not self._initialized:
            raise RuntimeError("Engine not initialized. Call init_engine() first.")
        result = self.engine.get_tokenizer()
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def shutdown(self):
        """Shutdown the engine."""
        if self.engine:
            # vLLM doesn't have explicit shutdown, but we can mark as uninitialized
            self._initialized = False
            self.engine = None


class AsyncVLLMBackend:
    """
    Backend wrapper for AsyncVLLMEngine.
    
    Provides a consistent interface compatible with SkyRL-Agent's AsyncInferBackend.
    """

    def __init__(
        self,
        engine: AsyncVLLMEngine,
        tokenizer: Any = None
    ):
        """
        Initialize the backend.
        
        Args:
            engine: AsyncVLLMEngine instance
            tokenizer: Optional tokenizer (will use engine's tokenizer if not provided)
        """
        self.engine = engine
        self._tokenizer = tokenizer

    @property
    def tokenizer(self):
        """Return the tokenizer, fetching from engine if needed."""
        if self._tokenizer is None:
            self._tokenizer = self.engine.get_tokenizer()
        return self._tokenizer

    async def async_generate_ids(
        self,
        input_ids: List[int],
        sampling_params: Dict[str, Any],
        request_id: str,
        **_kwargs  # Unused, for compatibility
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate from token IDs.
        
        Compatible with SkyRL-Agent's AsyncInferBackend interface.
        """
        return await self.engine.generate(
            prompt_ids=input_ids,
            sampling_params=sampling_params,
            request_id=request_id
        )

    async def async_generate_prompts(
        self,
        prompts: List[str],
        sampling_params: Dict[str, Any],
        **_kwargs  # Unused, for compatibility
    ) -> List[str]:
        """
        Generate from text prompts.
        
        Args:
            prompts: List of text prompts
            sampling_params: Sampling parameters
        
        Returns:
            List of generated texts
        """
        # Tokenize prompts
        all_input_ids = [
            self.tokenizer.encode(prompt)
            for prompt in prompts
        ]

        # Generate
        results = await self.engine.generate_batch(
            prompts=all_input_ids,
            sampling_params=sampling_params
        )

        return [text for text, _ in results]


# For Ray distributed deployment (like SkyRL-Agent)
def create_ray_vllm_actor(
    model_path: str,
    tensor_parallel_size: int = 1,
    **engine_args
):
    """
    Create a Ray actor wrapping AsyncVLLMEngine.

    Usage::

        import ray

        VLLMServer = create_ray_vllm_actor("meta-llama/Llama-3.1-8B-Instruct")
        server = VLLMServer.remote()
        ray.get(server.init_engine.remote())

        response, meta = ray.get(server.generate.remote(
            prompt_ids=[...],
            sampling_params={...},
            request_id="123",
        ))
    """
    if ray is None:
        raise ImportError(
            "ray is required for create_ray_vllm_actor. "
            "Install with: pip install mcpuniverse[vllm]"
        )

    @ray.remote(num_cpus=1)
    class RayVLLMServer(AsyncVLLMEngine):
        """Ray actor wrapping AsyncVLLMEngine for distributed deployment."""

        def __init__(self):
            super().__init__(
                model_path=model_path,
                tensor_parallel_size=tensor_parallel_size,
                **engine_args,
            )

    return RayVLLMServer
