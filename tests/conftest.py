"""Shared pytest configuration.

Disable the agent's post-edit diagnostics runner for the suite by default, so
whichever linters happen to be installed in the dev/CI environment can't change
the outcome of unrelated tests that write Python files. The feature is on by
default in real sessions and is exercised directly in
tests/test_agent_diagnostics.py, which opts back in.

Set at conftest import — before any agent module is imported — so the module's
import-time default and `configure()` both see it.
"""

from __future__ import annotations

import os

os.environ["ESSARION_NO_LINT_ON_EDIT"] = "1"
