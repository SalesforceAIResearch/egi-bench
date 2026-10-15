import json
import logging
from typing import List

from ..commons.types import Task

logger = logging.getLogger(__name__)


def load_tasks_from_jsonl(file_path: str) -> List[Task]:
    """
    Load tasks from a JSONL file.

    If a task doesn't have an id field, one will be automatically generated.
    """
    tasks = []
    with open(file_path, "r") as f:
        for line in f:
            task_data = json.loads(line)
            tasks.append(Task(**task_data))
    return tasks
