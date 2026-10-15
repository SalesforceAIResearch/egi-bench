"""
Tests for stats utilities

Tests token counting and PostProcessStats dataclass.
"""
import pytest
from mcpuniverse.extensions.mcpplus.utils.stats import count_tokens, PostProcessStats


class TestCountTokens:
    """Test suite for count_tokens function."""

    def test_empty_string(self):
        """Test token counting for empty string."""
        result = count_tokens("", model="gpt-4")
        assert result == 0

    def test_simple_text(self):
        """Test token counting for simple text."""
        text = "Hello world"
        result = count_tokens(text, model="gpt-4")
        assert result > 0
        assert isinstance(result, int)

    def test_longer_text(self):
        """Test that longer text has more tokens."""
        short_text = "Hi"
        long_text = "This is a much longer sentence with many more words and tokens."

        short_tokens = count_tokens(short_text, model="gpt-4")
        long_tokens = count_tokens(long_text, model="gpt-4")

        assert long_tokens > short_tokens

    def test_special_characters(self):
        """Test token counting with special characters."""
        text = "Hello! @#$% How are you? 😊"
        result = count_tokens(text, model="gpt-4")
        assert result > 0

    def test_json_text(self):
        """Test token counting for JSON-formatted text."""
        text = '{"name": "John", "age": 30, "city": "New York"}'
        result = count_tokens(text, model="gpt-4")
        assert result > 0

    def test_code_text(self):
        """Test token counting for code."""
        code = """
def hello_world():
    print("Hello, world!")
    return True
"""
        result = count_tokens(code, model="gpt-4")
        assert result > 0

    def test_different_models(self):
        """Test that different models can be specified."""
        text = "This is a test sentence."

        # These should all work without errors
        gpt4_tokens = count_tokens(text, model="gpt-4")
        gpt35_tokens = count_tokens(text, model="gpt-3.5-turbo")

        assert gpt4_tokens > 0
        assert gpt35_tokens > 0
        # Token counts may vary slightly between models, but should be close
        assert abs(gpt4_tokens - gpt35_tokens) <= 2

    def test_unicode_text(self):
        """Test token counting with Unicode characters."""
        text = "Hello 世界! Привет мир!"
        result = count_tokens(text, model="gpt-4")
        assert result > 0

    def test_very_long_text(self):
        """Test token counting for very long text."""
        text = "This is a sentence. " * 500  # ~3500 chars
        result = count_tokens(text, model="gpt-4")
        assert result > 100  # Should be many tokens

    def test_whitespace_handling(self):
        """Test that whitespace is counted appropriately."""
        text1 = "hello world"
        text2 = "hello    world"  # Multiple spaces
        text3 = "hello\nworld"  # Newline

        tokens1 = count_tokens(text1, model="gpt-4")
        tokens2 = count_tokens(text2, model="gpt-4")
        tokens3 = count_tokens(text3, model="gpt-4")

        # All should produce reasonable token counts
        assert tokens1 > 0
        assert tokens2 > 0
        assert tokens3 > 0

    def test_markdown_text(self):
        """Test token counting for markdown-formatted text."""
        text = """
# Heading

This is **bold** and this is *italic*.

- Item 1
- Item 2
- Item 3

[Link](https://example.com)
"""
        result = count_tokens(text, model="gpt-4")
        assert result > 10

    def test_html_text(self):
        """Test token counting for HTML."""
        html = """
<html>
<head><title>Test</title></head>
<body>
<h1>Hello</h1>
<p>This is a paragraph with <strong>bold</strong> text.</p>
</body>
</html>
"""
        result = count_tokens(html, model="gpt-4")
        assert result > 10


class TestPostProcessStats:
    """Test suite for PostProcessStats dataclass."""

    def test_initialization(self):
        """Test basic initialization of PostProcessStats."""
        stats = PostProcessStats(
            postprocessor_iterations=1,
            original_chars=1000,
            filtered_chars=500,
            chars_reduced=500,
            original_tokens=200,
            filtered_tokens=100,
            tokens_reduced=100,
            success=True
        )

        assert stats.postprocessor_iterations == 1
        assert stats.original_chars == 1000
        assert stats.filtered_chars == 500
        assert stats.chars_reduced == 500
        assert stats.original_tokens == 200
        assert stats.filtered_tokens == 100
        assert stats.tokens_reduced == 100
        assert stats.success is True

    def test_zero_reduction(self):
        """Test stats when no reduction occurred."""
        stats = PostProcessStats(
            postprocessor_iterations=1,
            original_chars=100,
            filtered_chars=100,
            chars_reduced=0,
            original_tokens=20,
            filtered_tokens=20,
            tokens_reduced=0,
            success=True
        )

        assert stats.chars_reduced == 0
        assert stats.tokens_reduced == 0

    def test_failed_processing(self):
        """Test stats for failed post-processing."""
        stats = PostProcessStats(
            postprocessor_iterations=3,
            original_chars=5000,
            filtered_chars=5000,
            chars_reduced=0,
            original_tokens=1000,
            filtered_tokens=1000,
            tokens_reduced=0,
            success=False
        )

        assert stats.success is False
        assert stats.postprocessor_iterations == 3

    def test_multiple_iterations(self):
        """Test stats with multiple iterations."""
        stats = PostProcessStats(
            postprocessor_iterations=3,
            original_chars=2000,
            filtered_chars=500,
            chars_reduced=1500,
            original_tokens=400,
            filtered_tokens=100,
            tokens_reduced=300,
            success=True
        )

        assert stats.postprocessor_iterations == 3
        assert stats.tokens_reduced == 300

    def test_high_reduction_rate(self):
        """Test stats with high reduction rate (70%+)."""
        stats = PostProcessStats(
            postprocessor_iterations=2,
            original_chars=10000,
            filtered_chars=2000,
            chars_reduced=8000,
            original_tokens=2000,
            filtered_tokens=400,
            tokens_reduced=1600,
            success=True
        )

        # Verify 80% token reduction
        reduction_rate = stats.tokens_reduced / stats.original_tokens
        assert reduction_rate == 0.8

    def test_minimal_reduction(self):
        """Test stats with minimal reduction."""
        stats = PostProcessStats(
            postprocessor_iterations=1,
            original_chars=1000,
            filtered_chars=950,
            chars_reduced=50,
            original_tokens=200,
            filtered_tokens=190,
            tokens_reduced=10,
            success=True
        )

        # Verify 5% token reduction
        reduction_rate = stats.tokens_reduced / stats.original_tokens
        assert reduction_rate == 0.05

    def test_dataclass_equality(self):
        """Test that two identical stats objects are equal."""
        stats1 = PostProcessStats(
            postprocessor_iterations=1,
            original_chars=100,
            filtered_chars=50,
            chars_reduced=50,
            original_tokens=20,
            filtered_tokens=10,
            tokens_reduced=10,
            success=True
        )

        stats2 = PostProcessStats(
            postprocessor_iterations=1,
            original_chars=100,
            filtered_chars=50,
            chars_reduced=50,
            original_tokens=20,
            filtered_tokens=10,
            tokens_reduced=10,
            success=True
        )

        assert stats1 == stats2

    def test_dataclass_inequality(self):
        """Test that different stats objects are not equal."""
        stats1 = PostProcessStats(
            postprocessor_iterations=1,
            original_chars=100,
            filtered_chars=50,
            chars_reduced=50,
            original_tokens=20,
            filtered_tokens=10,
            tokens_reduced=10,
            success=True
        )

        stats2 = PostProcessStats(
            postprocessor_iterations=2,
            original_chars=100,
            filtered_chars=50,
            chars_reduced=50,
            original_tokens=20,
            filtered_tokens=10,
            tokens_reduced=10,
            success=True
        )

        assert stats1 != stats2

    def test_realistic_example(self):
        """Test with realistic values from actual usage."""
        # Simulate: 10KB HTML page filtered to 2KB relevant content
        stats = PostProcessStats(
            postprocessor_iterations=1,
            original_chars=10240,
            filtered_chars=2048,
            chars_reduced=8192,
            original_tokens=2560,  # ~4 chars per token
            filtered_tokens=512,
            tokens_reduced=2048,
            success=True
        )

        assert stats.success is True
        # Verify ~80% reduction
        reduction_rate = stats.tokens_reduced / stats.original_tokens
        assert 0.79 <= reduction_rate <= 0.81
