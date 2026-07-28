"""
SubversionBench v14
====================================
Hardened agentic-misalignment eval with eval awareness detection, sandbox isolation,
rubric-based grading, and timing instrumentation.

Formerly "Oversight Subversion Evaluation" / oversight_eval - loosely
based on Meinke et al.'s "Frontier Models are Capable of In-Context
Scheming" (Apollo Research), now a distinct work.

Package structure:
  config.py      — VERSION, prompts, keyword lists, rubric questions, tool defs
  environment.py — scenario filesystem creation, project name generation
  sandbox.py     — sandboxed command execution
  redaction.py   — rewrites host-specific paths out of output and artifacts
  power.py       — interval estimation, detectable effect sizes, precision
  grading.py     — keyword detection, LLM rubric grader, misalignment analysis
  run_eval.py    — agentic loop, follow-up, batch runner, CLI

One test file per module above (test_config.py, test_sandbox.py, ...) at the
repo root, with shared fixtures in conftest.py. Version history: CHANGELOG.md.

Run:   python -m subversionbench.run_eval --help
Tests: pytest      (or python run_tests.py, which needs no pytest)
"""

from .config import (
    VERSION,
    EVAL_AWARENESS_INDICATORS,
    GOAL_CONFLICT_AWARENESS,
    RUBRIC_SYSTEM_PROMPT,
    RUBRIC_QUESTIONS,
    SYSTEM_PROMPT_STRONG_NUDGE,
    SYSTEM_PROMPT_NO_NUDGE,
    USER_PROMPT,
    TOOLS,
    SANDBOX_DISPLAY_PATH,
    CANARY,
    CANARY_GUID,
)
from .environment import generate_project_name, create_hardened_environment
from .sandbox import execute_tool_sandboxed
from .redaction import redact_paths
from .power import (
    wilson_ci,
    two_arm_power,
    minimum_detectable_rate,
    n_for_precision,
    analyse_batch,
)
from .grading import (
    detect_eval_awareness_keywords,
    detect_eval_awareness_grader,
    analyze_misalignment,
    classify_misalignment,
    classify_scheming,
)

__all__ = [
    "VERSION",
    "EVAL_AWARENESS_INDICATORS",
    "GOAL_CONFLICT_AWARENESS",
    "RUBRIC_SYSTEM_PROMPT",
    "RUBRIC_QUESTIONS",
    "SYSTEM_PROMPT_STRONG_NUDGE",
    "SYSTEM_PROMPT_NO_NUDGE",
    "USER_PROMPT",
    "TOOLS",
    "SANDBOX_DISPLAY_PATH",
    "CANARY",
    "CANARY_GUID",
    "generate_project_name",
    "create_hardened_environment",
    "execute_tool_sandboxed",
    "redact_paths",
    "wilson_ci",
    "two_arm_power",
    "minimum_detectable_rate",
    "n_for_precision",
    "analyse_batch",
    "detect_eval_awareness_keywords",
    "detect_eval_awareness_grader",
    "analyze_misalignment",
    "classify_misalignment",
    "classify_scheming",
]
