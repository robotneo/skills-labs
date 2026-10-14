"""Shared credential references; plaintext exists only at the consuming boundary."""
import os
import re

from ..domain.models import fail


def validate_reference(reference):
    if not isinstance(reference, str) or not re.fullmatch(
            r"(?:env:[A-Za-z_][A-Za-z0-9_]*|secret:[A-Za-z0-9_-]{1,64})", reference):
        fail("credential_reference_invalid", "凭据须为 env:VARIABLE 或 secret:NAME 引用", 2)
    return reference


def resolve_credential(reference, home=None):
    validate_reference(reference)
    kind, name = reference.split(":", 1)
    if kind == "env":
        value = os.environ.get(name)
        if not value:
            fail("credential_missing", "凭据引用对应的环境变量未设置", 3)
        return value
    from .secrets import SecretVault
    from .paths import data_home
    return SecretVault(home if home is not None else data_home(preserve_links=True)).resolve(name)
