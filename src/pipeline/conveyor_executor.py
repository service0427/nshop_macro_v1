#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/conveyor_executor.py

Modular Gateway for N-Shop Macro Execution Pipeline.
Delegates execution to src.pipeline.executor.execute_task_pipeline.
Maintains 100% backward compatibility with run.py and existing runners.
"""

from src.pipeline.models import (
    TaskInput,
    TaskResult,
    get_cdp_port,
    clean_keyword,
    shorten_keyword,
    save_task_history
)
from src.pipeline.executor import execute_task_pipeline

# Backward compatibility alias
async def execute_task(task: TaskInput):
    """
    Executes task using the modular 5-step pipeline.
    """
    return await execute_task_pipeline(task)

__all__ = [
    "TaskInput",
    "TaskResult",
    "get_cdp_port",
    "clean_keyword",
    "shorten_keyword",
    "save_task_history",
    "execute_task_pipeline",
    "execute_task"
]
