"""Shared command registration fragments."""
from ...domain.contracts import Parameter as P


WRITE_OPTIONS = (
    P("dry_run", "boolean", default=False),
    P("request_id"),
    P("wait", "boolean", default=True),
)
