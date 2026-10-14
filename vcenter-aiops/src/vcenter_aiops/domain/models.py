from dataclasses import dataclass, field
from typing import Any


class OperationError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 5):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


class SubmissionRejected(OperationError):
    """Provider guarantee: validation rejected before any remote write call.

    Never wrap exceptions from a write method, its response, or persistence.
    """


@dataclass
class Result:
    status: str = "succeeded"
    data: Any = None
    operation_id: str | None = None
    target: Any = None
    warnings: list = field(default_factory=list)
    error: Any = None
    next_action: Any = None

    def to_dict(self):
        return {"schema_version": "1", **self.__dict__}


def fail(code, message, exit_code=5):
    raise OperationError(code, message, exit_code)
