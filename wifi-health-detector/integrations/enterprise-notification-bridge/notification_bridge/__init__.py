from __future__ import absolute_import

from .contract import ContractError, build_envelope, validate_envelope
from .models import Envelope

# Single source of the bridge component version for Python code (MCP serverInfo,
# diagnostics). The packaging metadata (manifest.json, component.yaml) must match
# this value; test_agent_contracts enforces the three-way equality so they can
# never silently drift again.
__version__ = "1.0.6"

__all__ = [
    "ContractError", "Envelope", "__version__",
    "build_envelope", "validate_envelope",
]
