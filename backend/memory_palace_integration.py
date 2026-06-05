"""
Memory Palace — Integration layer re-export shim (Phase D1, 2026-06-05)
======================================================================

The implementation previously defined in this module has been merged
into :mod:`backend.memory_palace` as :class:`MemoryPalaceIntegration`
alongside the original Phase A :class:`MemoryPalace` (SQLite-only).

This shim preserves the public import path so that callers that
import from :mod:`backend.memory_palace_integration` continue to
work without modification. Two protected files depend on this path:

* :mod:`backend.memory_palace_integration_endpoint` (the C2 router)
* :mod:`backend.tests.test_memory_palace_integration` (12 unit tests)
* :mod:`backend.tests.test_memory_palace_integration_endpoint` (6 tests)

**Do NOT** add new code here — the source of truth is
:mod:`backend.memory_palace`. Any new feature goes there.
"""
from .memory_palace import (
    EMBEDDING_DIM,
    MemoryNotFoundError,
    MemoryPalaceIntegration,
    MemoryPalaceIntegrationError,
    SalienceOutOfRangeError,
    memories_table,
)

__all__ = [
    "MemoryPalaceIntegration",
    "MemoryPalaceIntegrationError",
    "SalienceOutOfRangeError",
    "MemoryNotFoundError",
    "memories_table",
    "EMBEDDING_DIM",
]
