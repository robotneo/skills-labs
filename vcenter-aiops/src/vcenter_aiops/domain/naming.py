"""Single product-wide vocabulary for managed-object names.

Every create/rename path (VM create, template clone, cluster create and the
folder pre-write placement check) must apply the same rules, instead of each
provider keeping its own copy of the regular expression. A name is acceptable
only when all of the following hold:

* it is a non-empty ``str`` of 1..``NAME_MAX`` characters;
* it contains no path separator (``/ \\``), percent (``%``) or ASCII control
  character (``\\x00``-``\\x1f``) — these break vCenter paths/display;
* it has no leading/trailing whitespace (``name.strip() == name``); interior
  spaces remain legal because paths never reach a shell;
* it carries no invisible / zero-width characters, which defeat exact-target
  human verification (same smuggling set the risk gate rejects).

The check is boolean on purpose: callers keep their own domain-specific
``name_invalid`` message and exit code. It performs no I/O and never raises.
"""
import re

NAME_MAX = 80

# Path/percent/control characters are never legal in a managed-object name.
_NAME_INVALID = re.compile(r"[/\\%\x00-\x1f]")

# Zero-width / invisible characters (copy-paste target smuggling). Kept in sync
# with risk._INVISIBLE_RE: ZWSP/ZWNJ/ZWJ, word joiner, BOM/no-break, soft hyphen,
# Mongolian vowel separator and the invisible math operators.
_INVISIBLE = re.compile(
    "["
    "\u200b\u200c\u200d\u2060\ufeff"
    "\u00ad\u180e"
    "\u2061\u2062\u2063\u2064"
    "]"
)


def valid_name(value, max_len=NAME_MAX):
    """Return True only for an acceptable, human-verifiable object name."""
    if not isinstance(value, str) or not value:
        return False
    if len(value) > max_len:
        return False
    if value.strip() != value:
        return False
    if _NAME_INVALID.search(value):
        return False
    if _INVISIBLE.search(value):
        return False
    return True


SNAPSHOT_NAME_MAX = 80

# Snapshot names are user labels (vCenter permits path/percent characters in
# them), so only control characters and invisible/zero-width markers are
# forbidden; separators such as "/", "\\" and "%" stay legal.
_SNAPSHOT_INVALID = re.compile(r"[\x00-\x1f]")


def valid_snapshot_name(value, max_len=SNAPSHOT_NAME_MAX):
    """Validate a snapshot label: bounded, no edge whitespace/control/zero-width.

    Unlike managed-object names, snapshot labels may contain path/percent
    characters; only characters that break the API or hide target identity are
    rejected.
    """
    if not isinstance(value, str) or not value:
        return False
    if len(value) > max_len:
        return False
    if value.strip() != value:
        return False
    if _SNAPSHOT_INVALID.search(value):
        return False
    if _INVISIBLE.search(value):
        return False
    return True
