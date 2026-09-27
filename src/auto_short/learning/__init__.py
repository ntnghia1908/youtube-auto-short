"""Chinese Learning: the second application of the host repository.

Canonical contract: docs/decisions/CL1-chinese-learning-contract.md (C1 host/application
convention, C4 namespace ``<workspace dir>/_learning/<video id>/``). CL1.1 implements the
``subtitle`` and ``media`` stages and the ``auto-short learn`` command; CL1.2 the AI stage ``lesson``.
"""

from .run import LEARNING_DIR, LearningError, LearningResult, learning_root, run_learning

__all__ = ["LEARNING_DIR", "LearningError", "LearningResult", "learning_root", "run_learning"]
