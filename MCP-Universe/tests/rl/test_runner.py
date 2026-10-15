"""Tests for mcpuniverse.rl.runner module."""

import pytest

from mcpuniverse.rl.runner import RolloutOutput, RolloutEngine
from mcpuniverse.rl.config import RolloutConfig, ServerConfig


class TestRolloutOutput:
    """Tests for RolloutOutput dataclass."""

    def test_default_creation(self):
        out = RolloutOutput()
        assert out.responses == []
        assert out.rewards == []
        assert out.finish_reasons == []
        assert out.trajectories == []
        assert out.rollout_metrics == {}

    def test_with_data(self):
        out = RolloutOutput(
            responses=["Answer 1", "Answer 2"],
            rewards=[1.0, 0.5],
            finish_reasons=["completed", "max_iterations"],
            rollout_metrics={"success_rate": 0.5, "mean_reward": 0.75},
        )
        assert len(out.responses) == 2
        assert out.rewards[0] == 1.0
        assert out.rollout_metrics["success_rate"] == 0.5

    def test_to_dict(self):
        out = RolloutOutput(
            responses=["Hello"],
            rewards=[1.0],
            finish_reasons=["completed"],
            rollout_metrics={"mean_steps": 3.0},
        )
        d = out.to_dict()
        assert isinstance(d, dict)
        assert d["responses"] == ["Hello"]
        assert d["rewards"] == [1.0]
        assert d["rollout_metrics"]["mean_steps"] == 3.0

    def test_get_trajectory_texts(self):
        out = RolloutOutput(
            responses=["Resp1", "Resp2"],
            trajectories=[
                {"full_trace_text": "trace1"},
                {"full_trace_text": "trace2"},
            ],
        )
        texts = out.get_trajectory_texts()
        assert isinstance(texts, list)

    def test_get_all_steps(self):
        out = RolloutOutput(
            responses=["R1"],
            trajectories=[{"steps": [{"type": "thought", "content": "think"}]}],
        )
        steps = out.get_all_steps()
        assert isinstance(steps, list)

    def test_get_all_messages(self):
        out = RolloutOutput(
            responses=["R1"],
            trajectories=[{"messages": [{"role": "user", "content": "hi"}]}],
        )
        messages = out.get_all_messages()
        assert isinstance(messages, list)


class TestRolloutEngine:
    """Tests for RolloutEngine class."""

    def test_engine_creation(self):
        config = RolloutConfig(
            llm_type="openai",
            llm_config={"model_name": "gpt-4o", "api_key": "test"},
        )
        engine = RolloutEngine(config)
        assert engine is not None

    def test_engine_update_model_endpoint(self):
        config = RolloutConfig(
            llm_type="vllm_local",
            llm_config={"base_url": "http://localhost:8000/v1"},
        )
        engine = RolloutEngine(config)
        engine.update_model_endpoint("http://localhost:9000/v1")

        endpoint = engine.get_model_endpoint()
        assert "9000" in endpoint

    def test_engine_update_llm_config(self):
        config = RolloutConfig(
            llm_type="openai",
            llm_config={"model_name": "gpt-4o", "api_key": "test"},
        )
        engine = RolloutEngine(config)
        engine.update_llm_config(temperature=0.5)
        # Should not raise
