"""
Exceptions raised by devops_tools. Each message says what went wrong and what to fix.
"""

from __future__ import annotations


class RunLogCleanupUsageError(Exception):
    """
    `prune-logs` got arguments it does not accept. The message says which and why.
    """


class CommandLineUsageError(Exception):
    """
    The command line is not one `devops-tools` accepts. The message says what is wrong.
    """


class RepositorySettingsError(Exception):
    """
    The `[tool.devops-tools]` table cannot be used. The message names the file and the key.
    """
