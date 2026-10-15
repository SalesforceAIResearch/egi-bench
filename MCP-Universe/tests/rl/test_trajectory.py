"""Tests for mcpuniverse.rl.trajectory module."""

import pytest

from mcpuniverse.rl.trajectory import (
    TrajectoryResult, TrajectoryStep, TraceData, TokenData,
)


class TestTrajectoryStep:
    """Tests for TrajectoryStep dataclass."""

    def test_basic_creation(self):
        step = TrajectoryStep(step_type="thought", content="Let me think...")
        assert step.step_type == "thought"
        assert step.content == "Let me think..."
        assert step.metadata == {}

    def test_with_metadata(self):
        step = TrajectoryStep(
            step_type="action",
            content='{"tool": "calculator", "args": {"a": 1}}',
            metadata={"tool_name": "calculator", "duration_ms": 150},
        )
        assert step.step_type == "action"
        assert step.metadata["tool_name"] == "calculator"
        assert step.metadata["duration_ms"] == 150

    def test_step_types(self):
        for stype in ["thought", "action", "action_input", "result", "answer", "error"]:
            step = TrajectoryStep(step_type=stype, content="test")
            assert step.step_type == stype

    def test_to_dict(self):
        step = TrajectoryStep(
            step_type="answer",
            content="The answer is 42",
            metadata={"confidence": 0.95},
        )
        if hasattr(step, "to_dict"):
            d = step.to_dict()
            assert d["type"] == "answer"
            assert d["content"] == "The answer is 42"


class TestTrajectoryResult:
    """Tests for TrajectoryResult dataclass."""

    def test_basic_creation(self):
        result = TrajectoryResult(
            instance_id="task_001",
            trajectory_id=0,
            response="The answer is 4",
            reward=1.0,
            finish_reason="completed",
        )
        assert result.instance_id == "task_001"
        assert result.trajectory_id == 0
        assert result.response == "The answer is 4"
        assert result.reward == 1.0
        assert result.finish_reason == "completed"

    def test_default_fields(self):
        result = TrajectoryResult(
            instance_id="t1",
            trajectory_id=0,
            response="ok",
            reward=0.5,
            finish_reason="done",
        )
        assert result.error is None
        assert result.trace_id is None
        # TraceData defaults
        assert result.trace.records == []
        assert result.trace.full_text == ""
        assert result.trace.prompt_text == ""
        assert result.trace.output_text == ""
        assert result.trace.output_segments == []
        assert result.num_steps == 0
        assert result.num_tool_calls == 0
        assert result.running_time == 0.0
        assert result.rollout_mode == "text"
        # TokenData defaults
        assert result.tokens.ids == []
        assert result.tokens.segments == []
        assert result.tokens.trainable_mask == []

    def test_with_all_fields(self):
        result = TrajectoryResult(
            instance_id="task_002",
            trajectory_id=1,
            response="Weather is sunny",
            reward=0.8,
            finish_reason="max_iterations",
            error=None,
            trace_id="trace_123",
            trace=TraceData(
                full_text="<|start|>system...",
                prompt_text="System prompt",
                output_text="Assistant response",
                output_segments=[
                    {"role": "assistant", "content": "sunny", "trainable": True},
                ],
            ),
            num_steps=3,
            num_tool_calls=1,
            running_time=2.5,
            rollout_mode="token",
            tokens=TokenData(
                ids=[1, 2, 3, 4, 5],
                trainable_mask=[False, False, True, True, True],
            ),
        )
        assert result.num_steps == 3
        assert result.num_tool_calls == 1
        assert result.running_time == 2.5
        assert result.rollout_mode == "token"
        assert len(result.tokens.ids) == 5
        assert len(result.tokens.trainable_mask) == 5

    def test_with_error(self):
        result = TrajectoryResult(
            instance_id="t3",
            trajectory_id=0,
            response="",
            reward=0.0,
            finish_reason="error",
            error="Timeout during tool call",
        )
        assert result.error == "Timeout during tool call"
        assert result.reward == 0.0

    def test_to_dict(self):
        result = TrajectoryResult(
            instance_id="t4",
            trajectory_id=0,
            response="Hello",
            reward=1.0,
            finish_reason="completed",
            num_steps=2,
            num_tool_calls=0,
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["instance_id"] == "t4"
        assert d["response"] == "Hello"
        assert d["reward"] == 1.0
        assert d["num_steps"] == 2

    def test_to_dict_flattens_sub_dataclasses(self):
        result = TrajectoryResult(
            instance_id="t_flat",
            trajectory_id=0,
            response="ok",
            reward=1.0,
            finish_reason="done",
            trace=TraceData(
                full_text="full",
                prompt_text="prompt",
                output_text="output",
            ),
            rollout_mode="token",
            tokens=TokenData(
                ids=[1, 2, 3],
                trainable_mask=[False, True, True],
            ),
        )
        d = result.to_dict()
        # to_dict() flattens TraceData and TokenData for backward compat
        assert d["full_trace_text"] == "full"
        assert d["prompt_text"] == "prompt"
        assert d["output_text"] == "output"
        assert d["token_ids"] == [1, 2, 3]
        assert d["trainable_mask"] == [False, True, True]

    def test_get_training_text(self):
        result = TrajectoryResult(
            instance_id="t5",
            trajectory_id=0,
            response="answer",
            reward=1.0,
            finish_reason="done",
            trace=TraceData(
                prompt_text="prompt part",
                output_text="output part",
            ),
        )
        text = result.get_training_text()
        assert isinstance(text, str)

    def test_get_training_tokens(self):
        result = TrajectoryResult(
            instance_id="t6",
            trajectory_id=0,
            response="answer",
            reward=1.0,
            finish_reason="done",
            tokens=TokenData(
                ids=[10, 20, 30],
                trainable_mask=[False, True, True],
                segments=[{"type": "prompt"}, {"type": "output"}, {"type": "output"}],
            ),
        )
        tokens = result.get_training_tokens()
        assert isinstance(tokens, dict)
        assert "token_ids" in tokens
        assert "trainable_mask" in tokens
