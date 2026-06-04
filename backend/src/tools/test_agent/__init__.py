"""
backend/src/tools/test_agent/__init__.py

位置：backend/src/tools/test_agent/
职责：test_agent 专属 mock tools 包入口。
      这些 tools 仅供 test_agent 使用，物理隔离在此目录，
      禁止出现在 search_agent / screen_agent / extract_agent 的 plan.yaml 中。

导出：5 个 mock tool 函数 + reset_flaky_counters 工具函数。
"""

from .mock_fail import mock_fail
from .mock_flaky import mock_flaky, reset_flaky_counters
from .mock_rich_output import mock_rich_output
from .mock_slow import mock_slow
from .mock_success import mock_success

__all__ = [
    "mock_success",
    "mock_fail",
    "mock_slow",
    "mock_flaky",
    "mock_rich_output",
    "reset_flaky_counters",
]
