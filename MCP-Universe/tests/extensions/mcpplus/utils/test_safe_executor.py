"""
Tests for SafeCodeExecutor

Tests the sandboxed code execution with security restrictions and timeout.
"""
import pytest
from mcpuniverse.extensions.mcpplus.utils.safe_executor import SafeCodeExecutor


class TestSafeCodeExecutor:
    """Test suite for SafeCodeExecutor."""

    def setup_method(self):
        """Set up test fixtures."""
        self.executor = SafeCodeExecutor(timeout=5)

    def test_simple_execution(self):
        """Test basic code execution."""
        code = "result = data.upper()"
        data = "hello world"

        result = self.executor.execute(code, data)
        assert result == "HELLO WORLD"

    def test_json_parsing(self):
        """Test JSON parsing in executed code."""
        code = """
import json
parsed = json.loads(data)
result = parsed['name']
"""
        data = '{"name": "John", "age": 30}'

        result = self.executor.execute(code, data)
        assert result == "John"

    def test_list_operations(self):
        """Test list filtering operations."""
        code = """
items = data.split(',')
result = [item.strip() for item in items if len(item.strip()) > 3]
"""
        data = "apple, pie, banana, kiwi"

        result = self.executor.execute(code, data)
        assert result == ["apple", "banana", "kiwi"]

    def test_dictionary_result(self):
        """Test returning dictionary results."""
        code = """
lines = data.split('\\n')
result = {'count': len(lines), 'first': lines[0] if lines else None}
"""
        data = "line1\nline2\nline3"

        result = self.executor.execute(code, data)
        assert result == {'count': 3, 'first': 'line1'}

    def test_no_result_returns_data(self):
        """Test that code without result assignment returns original data."""
        code = "x = 10 + 5"  # No result variable
        data = "original"

        result = self.executor.execute(code, data)
        assert result == "original"

    def test_dangerous_eval_blocked(self):
        """Test that eval() is blocked."""
        code = "result = eval('1 + 1')"
        data = "test"

        with pytest.raises(ValueError, match="Dangerous operation detected: eval"):
            self.executor.execute(code, data)

    def test_dangerous_exec_blocked(self):
        """Test that exec() is blocked."""
        code = "exec('print(123)')"
        data = "test"

        with pytest.raises(ValueError, match="Dangerous operation detected: exec"):
            self.executor.execute(code, data)

    def test_dangerous_os_system_blocked(self):
        """Test that os.system is blocked."""
        code = "import os; os.system('ls')"
        data = "test"

        with pytest.raises(ValueError, match="Dangerous operation detected: os.system"):
            self.executor.execute(code, data)

    def test_dangerous_subprocess_blocked(self):
        """Test that subprocess is blocked."""
        code = "import subprocess; subprocess.run(['ls'])"
        data = "test"

        with pytest.raises(ValueError, match="Dangerous operation detected: subprocess"):
            self.executor.execute(code, data)

    def test_dangerous_import_blocked(self):
        """Test that __import__ is blocked."""
        code = "__import__('os').system('ls')"
        data = "test"

        with pytest.raises(ValueError, match="Dangerous operation detected: __import__"):
            self.executor.execute(code, data)

    def test_dangerous_pickle_blocked(self):
        """Test that pickle is blocked."""
        code = "import pickle; pickle.loads(data)"
        data = b"test"

        with pytest.raises(ValueError, match="Dangerous operation detected: pickle"):
            self.executor.execute(code, data)

    def test_syntax_error(self):
        """Test handling of syntax errors."""
        code = "result = data.upper("  # Syntax error
        data = "test"

        with pytest.raises(SyntaxError):
            self.executor.execute(code, data)

    def test_name_error(self):
        """Test handling of undefined variables."""
        code = "result = undefined_variable"
        data = "test"

        with pytest.raises(ValueError, match="variable reference error"):
            self.executor.execute(code, data)

    def test_attribute_error(self):
        """Test handling of attribute errors."""
        code = "result = data.nonexistent_method()"
        data = "test"

        with pytest.raises(AttributeError):
            self.executor.execute(code, data)

    def test_timeout_protection(self):
        """Test that infinite loops are terminated."""
        executor = SafeCodeExecutor(timeout=1)
        code = "while True: pass"
        data = "test"

        # Note: Timeout only works on Unix systems
        # On Windows, this test will hang - skip or handle differently
        import platform
        if platform.system() != "Windows":
            with pytest.raises(TimeoutError):
                executor.execute(code, data)
        else:
            pytest.skip("Timeout not supported on Windows")

    def test_regex_extraction(self):
        """Test regex-based extraction."""
        code = """
import re
match = re.search(r'price: \\$(\\d+)', data)
result = match.group(1) if match else None
"""
        data = "The product price: $99 is great!"

        result = self.executor.execute(code, data)
        assert result == "99"

    def test_html_parsing(self):
        """Test HTML parsing with BeautifulSoup."""
        code = """
from bs4 import BeautifulSoup
soup = BeautifulSoup(data, 'html.parser')
result = soup.find('title').text if soup.find('title') else None
"""
        data = "<html><head><title>Test Page</title></head></html>"

        try:
            result = self.executor.execute(code, data)
            assert result == "Test Page"
        except ImportError:
            pytest.skip("BeautifulSoup not installed")

    def test_multiple_operations(self):
        """Test complex multi-step extraction."""
        code = """
lines = data.strip().split('\\n')
items = []
for line in lines:
    if '=' in line:
        key, value = line.split('=', 1)
        items.append({'key': key.strip(), 'value': value.strip()})
result = items
"""
        data = """
name = John Doe
age = 30
city = San Francisco
"""

        result = self.executor.execute(code, data)
        assert len(result) == 3
        assert result[0] == {'key': 'name', 'value': 'John Doe'}
        assert result[1] == {'key': 'age', 'value': '30'}

    def test_empty_result_handling(self):
        """Test handling of explicit None result."""
        code = "result = None if data == 'empty' else 'value'"
        data = "empty"

        result = self.executor.execute(code, data)
        assert result == "empty"  # Returns data when result is None

    def test_case_insensitive_blocking(self):
        """Test that dangerous operations are blocked case-insensitively."""
        code = "RESULT = EVAL('1+1')"
        data = "test"

        with pytest.raises(ValueError, match="Dangerous operation detected"):
            self.executor.execute(code, data)
