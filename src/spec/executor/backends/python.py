"""
python backend: Execute registered Python callables in-process.

Calls a function by name from a registry, passes the payload as kwargs,
captures the return value as structured data in StepCapture.assessments.
Exit code is derived from the return value (the callable contract).

Callable contract:
  - Receives: (payload: dict, repo_path: Path, **kwargs) -> dict
  - Must return a dict with at least:
      "passed": bool
      "data": dict (structured result, stored in assessments)
  - May optionally include:
      "summary": str (human-readable summary, written to stdout.txt)

Payload schema:
  callable: str - Registered function name (e.g., "governance.validate_build")
  Plus any additional keys passed as the payload dict to the callable.
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec.executor.backends.base import BackendBase, BackendError

if TYPE_CHECKING:
    from spec.executor.schemas import Policy, StepCapture, StepManifest

# Registry of callable functions
_CALLABLES: dict[str, Callable[..., dict[str, Any]]] = {}


def register_callable(name: str, fn: Callable[..., dict[str, Any]]) -> None:
    """Register a callable function for the python backend.

    Args:
        name: Dotted name (e.g., "governance.validate_build").
        fn: Function matching the callable contract.
    """
    _CALLABLES[name] = fn


def get_callable(name: str) -> Callable[..., dict[str, Any]] | None:
    """Get a registered callable by name."""
    return _CALLABLES.get(name)


def list_callables() -> list[str]:
    """List all registered callable names."""
    return sorted(_CALLABLES.keys())


class PythonBackend(BackendBase):
    """In-process Python callable execution backend."""

    @property
    def name(self) -> str:
        return "python"

    def dispatch(
        self,
        manifest: StepManifest,
        artifacts_dir: Path,
        policy: Policy,
        capture_patch: bool = False,
    ) -> StepCapture:
        """Call a registered Python function and capture results."""
        from spec.executor.schemas import AgentCapture, StepCapture

        payload = dict(manifest.payload)
        common = manifest.common

        # Extract callable name
        callable_name = payload.pop("callable", None)
        if not callable_name:
            raise BackendError(
                "python backend requires 'callable' in payload",
                backend=self.name,
                step_id=manifest.step_id,
            )

        fn = get_callable(callable_name)
        if fn is None:
            available = ", ".join(list_callables()) or "(none)"
            raise BackendError(
                f"Unknown callable '{callable_name}'. Available: {available}",
                backend=self.name,
                step_id=manifest.step_id,
            )

        artifacts_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = artifacts_dir / "stdout.txt"
        stderr_path = artifacts_dir / "stderr.txt"
        result_path = artifacts_dir / "result.json"

        # Call the function
        try:
            result = fn(payload=payload, repo_path=Path(common.repo_path))
        except Exception:
            tb = traceback.format_exc()
            stderr_path.write_text(f"Callable '{callable_name}' raised:\n{tb}\n")
            stdout_path.write_text("")
            return StepCapture(
                step_n=manifest.step_n,
                step_id=manifest.step_id,
                agent=AgentCapture(
                    stdout_file=stdout_path.name,
                    stderr_file=stderr_path.name,
                    exit_code=1,
                ),
            )

        # Extract structured data
        passed = result.get("passed", False)
        data = result.get("data", result)
        summary = result.get("summary", "")

        # Write artifacts
        result_path.write_text(json.dumps(data, indent=2, default=str))
        stdout_path.write_text(summary or json.dumps(data, indent=2, default=str))
        stderr_path.write_text("")

        return StepCapture(
            step_n=manifest.step_n,
            step_id=manifest.step_id,
            agent=AgentCapture(
                stdout_file=stdout_path.name,
                stderr_file=stderr_path.name,
                exit_code=0 if passed else 1,
            ),
            assessments=[data],
        )
