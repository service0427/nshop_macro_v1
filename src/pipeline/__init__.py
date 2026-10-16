#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/__init__.py
"""

from src.pipeline.models import TaskInput, TaskResult, get_cdp_port, clean_keyword, shorten_keyword
from src.pipeline.executor import execute_task_pipeline

# Alias for backward compatibility
execute_task = execute_task_pipeline

__all__ = [
    "TaskInput",
    "TaskResult",
    "execute_task",
    "execute_task_pipeline",
    "get_cdp_port",
    "clean_keyword",
    "shorten_keyword"
]
