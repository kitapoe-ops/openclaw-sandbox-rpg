"""
Physics Lock v2.0 — re-export from the semantic state machine
=============================================================

The PhysicsLock implementation moved into :mod:`backend.state_machine`
in Phase F1-wide (2026-06-05) as part of the freeze-and-replace
refactor. The semantic state machine owns Physics Lock now because
the gate logic *is* part of state machine territory (audit invariant
#17-19 — "actions validated against state").

This module is a **one-line re-export** so that frozen callers
(:mod:`backend.choice_validator`) can keep importing
``from .physics_lock import PhysicsLock`` without modification.

The class, its constructor, and all its methods are **identical** to
the legacy implementation. There is no logic here; the source of
truth is :mod:`backend.state_machine`.

Note: the legacy v2.0 implementation is preserved in git history
(commit prior to F1-wide). The `DEFAULT_FORBIDDEN_ACTIONS` map is
re-exported for any code that imported it directly.
"""
from .state_machine import (
    DEFAULT_FORBIDDEN_ACTIONS,
    PhysicsLock,
)

__all__ = ["PhysicsLock", "DEFAULT_FORBIDDEN_ACTIONS"]
