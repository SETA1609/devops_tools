"""
Exceptions raised by devops_tools. Each message says what went wrong and what to fix.
"""

from __future__ import annotations


class RunLogCleanupUsageError(Exception):
    """
    `prune-logs` got arguments it does not accept. The message says which and why.
    """
