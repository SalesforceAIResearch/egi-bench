"""
Task definition and management for LoCoBench
"""

from typing import Dict, List, Optional, Any, Union
from enum import Enum
from dataclasses import dataclass


class TaskCategory(Enum):
    """Task categories for LoCoBench"""
    ARCHITECTURAL_UNDERSTANDING = "architectural_understanding"
    CROSS_FILE_REFACTORING = "cross_file_refactoring"
    FEATURE_IMPLEMENTATION = "feature_implementation"
    BUG_INVESTIGATION = "bug_investigation"
    MULTI_SESSION_DEVELOPMENT = "multi_session_development"
    CODE_COMPREHENSION = "code_comprehension"
    INTEGRATION_TESTING = "integration_testing"
    SECURITY_ANALYSIS = "security_analysis"


class DifficultyLevel(Enum):
    """Difficulty levels for tasks"""
    EASY = "easy"
    MEDIUM = "medium" 
    HARD = "hard"
    EXPERT = "expert"


@dataclass
class Task:
    """Represents a single evaluation task"""
    id: str
    category: TaskCategory
    difficulty: DifficultyLevel
    description: str
    context_files: List[str]
    context_length: int
    information_coverage: float
    session_count: int = 1
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def __repr__(self):
        return f"Task(id='{self.id}', category={self.category.value}, difficulty={self.difficulty.value})" 