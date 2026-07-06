"""
Module: scripts.cli.response

Uniform JSON envelope for every action handler.

All actions must return a :class:`Response`. ``handler.py`` centralises the
``json.dumps`` + ``print`` step through :meth:`Response.emit` so we do not
repeat the same 3-line block dozens of times.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Status constants (kept as plain strings to preserve the historical JSON
# contract expected by downstream tools).
# ---------------------------------------------------------------------------

class Status:
    """Response status vocabulary. Values match the pre-refactor strings."""

    SUCCESS = "success"
    WARNING = "warning"
    FAIL = "fail"
    DENIED = "denied"
    BLOCKED = "blocked"
    DRY_RUN = "dry_run"
    CONFIRM_REQUIRED = "confirm_required"
    ERROR = "error"


@dataclass
class Response:
    """Structured response returned by every action handler."""

    action: str
    status: str = Status.SUCCESS
    data: Any = None
    message: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)
    # When ``True``, ``data`` is omitted from the wire payload. Used by
    # dry-run responses whose historical envelope was ``{status, action,
    # params, message}`` without a ``data`` slot.
    omit_data: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialise into the historical wire format.

        Default envelope: ``{status, action, data, message}``. Callers that
        need the historical dry-run envelope should set :attr:`omit_data`.
        """
        payload: Dict[str, Any] = {
            "status": self.status,
            "action": self.action,
        }
        if not self.omit_data:
            payload["data"] = self.data
        # ``extras`` is merged before ``message`` so we can inject
        # per-action fields (e.g. ``params`` for dry-run) in the same slot
        # they previously occupied.
        if self.extras:
            payload.update(self.extras)
        payload["message"] = self.message
        return payload

    def emit(self, stream=sys.stdout) -> None:
        """Write the response as pretty-printed UTF-8 JSON to ``stream``."""
        stream.write(json.dumps(self.to_dict(), ensure_ascii=False, indent=2))
        stream.write("\n")

    # ------------------------------------------------------------------
    # Convenience factories
    # ------------------------------------------------------------------

    @classmethod
    def ok(cls, action: str, message: str = "", data: Any = None) -> "Response":
        return cls(action=action, status=Status.SUCCESS, message=message, data=data)

    @classmethod
    def fail(cls, action: str, message: str, data: Any = None) -> "Response":
        return cls(action=action, status=Status.FAIL, message=message, data=data)

    @classmethod
    def warning(cls, action: str, message: str, data: Any = None) -> "Response":
        return cls(action=action, status=Status.WARNING, message=message, data=data)

    @classmethod
    def error(cls, action: str, message: str) -> "Response":
        return cls(action=action, status=Status.ERROR, message=message)

    @classmethod
    def dry_run(cls, action: str, params: Optional[Dict[str, Any]] = None) -> "Response":
        # Historical envelope has no ``data`` field for dry-run; ``params``
        # sits between ``action`` and ``message``.
        response = cls(
            action=action,
            status=Status.DRY_RUN,
            message="Dry-Run 模式，未执行任何操作",
            omit_data=True,
        )
        response.extras["params"] = params or {}
        return response
