import logging
from logging.config import dictConfig
import os
from contextvars import ContextVar
import uuid

from typing import Optional

# Context variable for storing trace ID
trace_id_context: ContextVar[str] = ContextVar('trace_id', default='')

def get_trace_id() -> str:
    """Get current trace ID from context"""
    return trace_id_context.get()

def set_trace_id(trace_id: Optional[str] = None) -> str:
    """Set trace ID in context, generate new one if not provided"""
    if trace_id is None:
        trace_id = str(uuid.uuid4())[:8]
    trace_id_context.set(trace_id)
    return trace_id

class TraceIdFormatter(logging.Formatter):
    def __init__(self, *args, project_root: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        # 把项目根目录传进来
        self.project_root = project_root or os.getcwd()

    def format(self, record: logging.LogRecord) -> str:
        record.rel_path = os.path.relpath(record.pathname, self.project_root)
        record.trace_id = get_trace_id() or 'unknown'
        return super().format(record)

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": TraceIdFormatter,
            "fmt": "%(asctime)s.%(msecs)03d | %(levelname)s | %(trace_id)s | %(name)s | %(rel_path)s:%(lineno)d | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "root": {
        "handlers": ["default"],
        "level": "INFO"
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "autosubrt": {"handlers": ["default"], "level": "INFO", "propagate": False}
    },
}

dictConfig(LOGGING_CONFIG)

logger = logging.getLogger(__name__)
