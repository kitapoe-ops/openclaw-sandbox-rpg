"""
Tests for the 4 Phase D audit functions appended to
backend/r1_audit_client.py.

These tests are INTENTIONALLY network-free. The audit functions call
LM Studio at runtime, which is not available in CI. What we CAN
guarantee without LM Studio: the functions exist, are callable, take
the (repo_root: str = '.') contract, and carry docstrings.

If any of these tests fail, a Phase D subagent has either renamed /
removed one of the 4 new functions, changed the signature, or stripped
the docstring. All of these would break the playbook and the CI gate.
"""
from __future__ import annotations

import inspect
import os
import sys

_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# The 4 Phase D functions under test (single tuple for parametrization)
_D_FUNCTIONS = (
    "audit_phase_d1_merge",
    "audit_phase_d3_repository",
    "audit_phase_d5_pi5_deploy",
    "audit_phase_d6_llm_client",
)


def _load_d_functions():
    """Lazy import so test collection never fails on partial renames."""
    import backend.r1_audit_client as m
    return {name: getattr(m, name) for name in _D_FUNCTIONS}


# ============================================
# Tests
# ============================================


def test_d1_function_exists_and_callable() -> None:
    """audit_phase_d1_merge must be importable and callable."""
    fns = _load_d_functions()
    assert callable(fns["audit_phase_d1_merge"]), (
        "audit_phase_d1_merge must be a callable (async function). "
        "If you renamed it, update docs/AUDIT_PLAYBOOK.md and the D1 brief."
    )


def test_d3_function_exists_and_callable() -> None:
    """audit_phase_d3_repository must be importable and callable."""
    fns = _load_d_functions()
    assert callable(fns["audit_phase_d3_repository"]), (
        "audit_phase_d3_repository must be a callable (async function). "
        "If you renamed it, update docs/AUDIT_PLAYBOOK.md and the D3 brief."
    )


def test_d5_function_exists_and_callable() -> None:
    """audit_phase_d5_pi5_deploy must be importable and callable."""
    fns = _load_d_functions()
    assert callable(fns["audit_phase_d5_pi5_deploy"]), (
        "audit_phase_d5_pi5_deploy must be a callable (async function). "
        "If you renamed it, update docs/AUDIT_PLAYBOOK.md and the D5 brief."
    )


def test_d6_function_exists_and_callable() -> None:
    """audit_phase_d6_llm_client must be importable and callable."""
    fns = _load_d_functions()
    assert callable(fns["audit_phase_d6_llm_client"]), (
        "audit_phase_d6_llm_client must be a callable (async function). "
        "If you renamed it, update docs/AUDIT_PLAYBOOK.md and the D6 brief."
    )


def test_all_d_functions_have_docstrings() -> None:
    """Every Phase D audit function must carry a docstring (audit-trail)."""
    fns = _load_d_functions()
    for name, fn in fns.items():
        doc = fn.__doc__
        assert doc is not None and doc.strip(), (
            f"{name} is missing a docstring. Each Phase D audit function "
            "must document: scope, target files, and the specific concerns "
            "it asks R1 to verify."
        )
        # grep-ability: docstring should mention "Phase D"
        assert "Phase D" in doc, (
            f"{name} docstring should reference 'Phase D' for grep-ability."
        )


def test_d_functions_take_repo_root_kwarg() -> None:
    """All 4 Phase D functions must accept (repo_root: str = '.') like the
    3 historical rounds. This is the contract the playbook documents and
    that subagents rely on when invoking audits from the CLI."""
    fns = _load_d_functions()
    for name, fn in fns.items():
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        assert params, f"{name} must accept at least one parameter (repo_root)"
        assert params[0].name == "repo_root", (
            f"{name} first parameter must be 'repo_root', got '{params[0].name}'"
        )
        assert params[0].default == ".", (
            f"{name} default for 'repo_root' should be '.' (current dir), "
            f"got {params[0].default!r}"
        )
        assert sig.return_annotation != inspect.Signature.empty, (
            f"{name} should declare a return annotation"
        )
