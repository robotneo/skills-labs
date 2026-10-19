"""Centralised risk classification and pre-execution control policy.

Importing this module never loads the vSphere SDK. It is the single source of
truth for the three-tier risk model used by the interactive CLI gate:

* ``low``      - read-only, side-effect free. Runs directly.
* ``medium``   - sensitive but reversible / additive. The blast radius is
                 explained and an explicit confirmation is required.
* ``high``     - irreversible (delete / clear / overwrite / bulk / terminate).
                 Precise targets (resource, path, scope, count) are listed and
                 re-checked; fuzzy matching and broad wildcards are rejected;
                 a second, exact confirmation is required.

Engine-backed ``remote_write`` commands already obtain a stronger cryptographic
confirmation (plan digest, plus ``DESTROY:<digest>`` for destructive steps), so
the interactive gate only adds the human impact/target banner for them. The
gate fully enforces confirmation for *direct-effect* commands that bypass the
plan engine (local writes, guest file transfer, exports).
"""
import re

# ---- Risk levels -----------------------------------------------------------
LOW = "low"          # read-only query / preview
MEDIUM = "medium"    # sensitive change, reversible or additive
HIGH = "high"        # irreversible / bulk / termination

RISK_LEVELS = (LOW, MEDIUM, HIGH)

# ---- Sensitive categories (need impact statement + confirmation) ----------
PERMISSION_CHANGE = "permission_change"   # 权限/凭据/连接配置变更
DATA_EXPORT = "data_export"               # 数据外发/导出到文件或来宾
SYSTEM_CONFIG = "system_config"           # 系统/集群/VM 配置修改
OUTBOUND_SEND = "outbound_send"           # 对外发送信息/在来宾执行
PROCESS_TERMINATION = "process_termination"  # 终止进程/任务

SENSITIVE_CATEGORIES = (PERMISSION_CHANGE, DATA_EXPORT, SYSTEM_CONFIG,
                        OUTBOUND_SEND, PROCESS_TERMINATION)

# ---- Irreversible categories (need precise targets + second confirmation) --
IRREVERSIBLE_DELETE = "delete"
IRREVERSIBLE_CLEAR = "clear"
IRREVERSIBLE_OVERWRITE = "overwrite"
IRREVERSIBLE_BULK = "bulk_modify"
IRREVERSIBLE_TERMINATE = "terminate"

IRREVERSIBLE_CATEGORIES = (IRREVERSIBLE_DELETE, IRREVERSIBLE_CLEAR,
                           IRREVERSIBLE_OVERWRITE, IRREVERSIBLE_BULK,
                           IRREVERSIBLE_TERMINATE)

# Explicit per-command policy. Only commands that the generic derivation does
# not classify correctly appear here. Values are (level, sensitive, irrevers.).
# Remote engine writes (power/clone/deploy/reconfigure/guest-exec/...) are not
# listed: they inherit risk=change -> medium and are gated by the plan digest.
_OVERRIDES = {
    # ---- direct-effect local writes: secrets / profiles ------------------
    "secret set":      (MEDIUM, (PERMISSION_CHANGE,), ()),
    "secret rotate":   (HIGH, (PERMISSION_CHANGE,), (IRREVERSIBLE_OVERWRITE,)),
    "secret delete":   (HIGH, (PERMISSION_CHANGE,), (IRREVERSIBLE_DELETE,)),
    "profile add":     (MEDIUM, (PERMISSION_CHANGE, SYSTEM_CONFIG), ()),
    "profile update":  (MEDIUM, (PERMISSION_CHANGE, SYSTEM_CONFIG), ()),
    "profile delete":  (HIGH, (PERMISSION_CHANGE,), (IRREVERSIBLE_DELETE,)),
    # ---- local IP ledger / plan / cache / presets ------------------------
    "ip reserve":      (MEDIUM, (SYSTEM_CONFIG,), ()),
    "ip release":      (HIGH, (), (IRREVERSIBLE_DELETE,)),
    "plan archive":    (MEDIUM, (), ()),
    "cache invalidate": (HIGH, (), (IRREVERSIBLE_CLEAR,)),
    "preset save":     (MEDIUM, (), ()),
    "preset delete":   (HIGH, (), (IRREVERSIBLE_DELETE,)),
    "preset from-history": (MEDIUM, (), ()),
    "preset from-vm":  (MEDIUM, (), ()),
    # ---- data export / egress --------------------------------------------
    "audit export":    (MEDIUM, (DATA_EXPORT,), ()),
    "inventory export": (MEDIUM, (DATA_EXPORT,), ()),
    # ---- guest file transfer (direct effect, no plan engine) --------------
    "vm guest-download": (MEDIUM, (DATA_EXPORT,), ()),
    "vm guest-upload":   (MEDIUM, (OUTBOUND_SEND,), ()),
    # ---- bulk power over many VMs (plan engine, but amplified blast) ------
    "batch power-on":  (HIGH, (SYSTEM_CONFIG,), (IRREVERSIBLE_BULK,)),
    "batch power-off": (HIGH, (SYSTEM_CONFIG,), (IRREVERSIBLE_BULK, IRREVERSIBLE_TERMINATE)),
    "batch shutdown":  (HIGH, (SYSTEM_CONFIG,), (IRREVERSIBLE_BULK,)),
    "batch reset":     (HIGH, (SYSTEM_CONFIG,), (IRREVERSIBLE_BULK, IRREVERSIBLE_TERMINATE)),
    # ---- task termination (engine already requires exact task id) --------
    "task cancel":     (MEDIUM, (PROCESS_TERMINATION,), ()),
}

# Parameter names that carry a precise managed-object / resource identity.
_TARGET_FIELDS = (
    "vm_id", "host_id", "cluster_id", "datastore_id", "pool_id", "folder_id",
    "network_id", "entity_id", "alarm_id", "snapshot_id", "source_vm_id",
    "target_vm_id", "resource_pool_id", "parent_uuid", "search_id",
)
_PATH_FIELDS = ("file", "guest_path", "source", "spec_file", "work_dir")
_NAME_FIELDS = ("name", "new_name", "lease_id", "plan_id", "operation_id")

# A targeting value must be an explicit identifier/path. Reject shell globs,
# regex-ish quantifiers and SQL LIKE wildcards, i.e. fuzzy/broad selection.
# Whitespace is intentionally allowed because legitimate local file paths may
# contain spaces; the value is never passed to a shell, so spaces carry no
# injection risk here.
_WILDCARD_RE = re.compile(r"[\*\?\[\]{}%]|(\.[\*\+])")

# Invisible / zero-width characters defeat human verification of an exact target
# (copy-paste smuggling). They are never legitimate in a managed-object id, file
# path or scope value here, so their mere presence makes the target non-exact.
# Covers ZWSP/ZWNJ/ZWJ, word joiner, BOM/no-break, soft hyphen, Mongolian vowel
# separator and the invisible mathematical function/application operators.
_INVISIBLE_RE = re.compile(
    "["
    "\u200b\u200c\u200d\u2060\ufeff"  # ZWSP, ZWNJ, ZWJ, word joiner, BOM
    "\u00ad\u180e"                     # soft hyphen, Mongolian vowel separator
    "\u2061\u2062\u2063\u2064"         # invisible math function/application operators
    "]"
)


def is_wildcard(value):
    """True when a targeting value looks fuzzy rather than exact."""
    if not isinstance(value, str) or not value:
        return True
    # Only whitespace (spaces/tabs/ideographic space/...) carries no real target.
    if not value.strip():
        return True
    if _INVISIBLE_RE.search(value):
        return True
    return bool(_WILDCARD_RE.search(value))


def risk_level(spec, params=None):
    """Three-tier level for a command, accounting for runtime parameters."""
    params = params or {}
    # `ip expire` is read-only unless it actually releases a precise lease.
    if spec.path == "ip expire" and params.get("apply"):
        return HIGH
    override = _OVERRIDES.get(spec.path)
    level = override[0] if override else {"destructive": HIGH, "change": MEDIUM}.get(spec.risk, LOW)
    # guest-upload only becomes irreversible (overwrite) when explicitly asked.
    if spec.path == "vm guest-upload" and params.get("overwrite"):
        level = HIGH
    return level


def risk_tags(spec, params=None):
    """Return (sensitive_categories, irreversible_categories) for a command."""
    params = params or {}
    if spec.path == "ip expire" and params.get("apply"):
        return (SYSTEM_CONFIG,), (IRREVERSIBLE_DELETE,)
    override = _OVERRIDES.get(spec.path)
    if override:
        sensitive, irreversible = list(override[1]), list(override[2])
    elif spec.risk == "destructive":
        sensitive, irreversible = [SYSTEM_CONFIG], [IRREVERSIBLE_DELETE]
    elif spec.risk == "change":
        sensitive, irreversible = [SYSTEM_CONFIG], []
    else:
        sensitive, irreversible = [], []
    if spec.path == "vm guest-upload" and params.get("overwrite") \
            and IRREVERSIBLE_OVERWRITE not in irreversible:
        irreversible = [*irreversible, IRREVERSIBLE_OVERWRITE]
    return tuple(sensitive), tuple(irreversible)


def is_direct_effect(spec, params=None):
    """Commands whose handler applies the effect without the plan engine."""
    params = params or {}
    if spec.path == "ip expire" and params.get("apply"):
        return True
    if spec.category == "local_write":
        return True
    return spec.path in ("vm guest-upload", "vm guest-download",
                         "inventory export", "audit export")


def precise_targets(spec, params):
    """Extract exact, human-checkable targets: resource / path / scope / count.

    Returns a dict with ``resources``, ``paths``, ``scopes`` and ``count``.
    Bulk commands enumerate every identifier individually and never collapse
    them into a range or wildcard.
    """
    params = params or {}
    resources, paths, scopes = [], [], []

    def add(value, kind):
        if isinstance(value, str) and value:
            resources.append({"kind": kind, "id": value})

    # Bulk: enumerate each exact VM id (the batch handler already bounds the
    # list to 1-100 unique exact ids; re-state the count prominently).
    if spec.path.startswith("batch "):
        ids = params.get("vm_ids") or []
        for idx, vm_id in enumerate(ids, 1):
            resources.append({"kind": "vm", "id": vm_id, "index": idx})
    else:
        for field_name in _TARGET_FIELDS:
            if field_name in params:
                kind = "vm" if field_name in ("vm_id", "source_vm_id", "target_vm_id") else \
                       "host" if field_name == "host_id" else \
                       "cluster" if field_name == "cluster_id" else \
                       "datastore" if field_name == "datastore_id" else \
                       "pool" if field_name in ("pool_id", "resource_pool_id") else \
                       "folder" if field_name == "folder_id" else \
                       "network" if field_name == "network_id" else \
                       "snapshot" if field_name == "snapshot_id" else \
                       field_name.split("_")[0]
                add(params[field_name], kind)

    for field_name in _PATH_FIELDS:
        value = params.get(field_name)
        if isinstance(value, str) and value:
            paths.append({"field": field_name, "path": value})

    if "scope" in params and isinstance(params["scope"], str):
        scopes.append({"kind": "ip_scope", "value": params["scope"]})
    # IP reservation states exactly which address/owner is affected.
    if spec.path == "ip reserve":
        if params.get("ip"):
            scopes.append({"kind": "ip", "value": params["ip"]})
        if params.get("owner"):
            scopes.append({"kind": "owner", "value": params["owner"]})
    # `ip expire --apply <lease_id>` releases one precise lease.
    if spec.path == "ip expire" and params.get("apply") and params.get("lease_id"):
        resources.append({"kind": "lease_id", "id": params["lease_id"]})
    if "entity_type" in params:
        scopes.append({"kind": "entity_type", "value": params["entity_type"]})
    if "kind" in params and spec.path in ("cache invalidate", "cache refresh",
                                          "inventory list", "inventory export"):
        scopes.append({"kind": "asset_kind", "value": params["kind"]})
    # Exact named local objects.
    for field_name in _NAME_FIELDS:
        if field_name in params and isinstance(params[field_name], str) \
                and not resources and spec.category == "local_write":
            resources.append({"kind": field_name, "id": params[field_name]})

    count = len(resources) + len(paths) + len(scopes)
    if spec.path.startswith("batch "):
        count = len(params.get("vm_ids") or [])
    return {"resources": resources, "paths": paths, "scopes": scopes,
            "count": count, "bulk": spec.path.startswith("batch ")}


def validate_exact_targets(spec, params):
    """Reject fuzzy / wildcard / overly broad targeting for high-risk commands.

    Raises ``ValueError`` with a human message; the CLI maps it to exit code 2.
    """
    targets = precise_targets(spec, params)
    if spec.path.startswith("batch "):
        ids = (params or {}).get("vm_ids") or []
        if not ids or len(ids) > 100:
            raise ValueError("批量操作须提供 1–100 个目标")
        if len(set(ids)) != len(ids):
            raise ValueError("批量目标存在重复，须逐个枚举且不重复")
        for vm_id in ids:
            if is_wildcard(vm_id):
                raise ValueError(f"批量目标含模糊/通配标识：{vm_id!r}；须给出精确 vm-N")
        return targets
    for item in targets["resources"] + targets["paths"] + targets["scopes"]:
        value = item.get("id") or item.get("path") or item.get("value")
        if is_wildcard(value):
            raise ValueError(f"目标 {value!r} 含通配或空白；禁止模糊匹配，须提供精确标识/路径")
    return targets


def confirmation_token(spec, params, profile=None):
    """The exact string a user must retype for a high-risk direct command.

    ``profile`` is the resolved global ``--profile`` scope. It is required to
    bind the token for commands whose only targeting parameter is not a managed
    object/path — notably ``cache invalidate``, which clears *all recorded
    servers* for one profile+kind. Without that binding the token would collapse
    to the constant command path and could be replayed across scopes.
    """
    params = params or {}
    if spec.path.startswith("batch "):
        ids = params.get("vm_ids") or []
        return str(len(ids))
    if spec.path == "cache invalidate":
        kind = params.get("kind")
        # profile is [A-Za-z0-9_-]{1,64} (validated elsewhere); kind is a fixed
        # enum. Refuse to emit a scope-bound token without either (fail-closed).
        if not isinstance(profile, str) or not profile or not isinstance(kind, str) or not kind:
            raise ValueError("cache invalidate 的确认令牌必须绑定明确的 Profile 和资产类型")
        return f"cache invalidate:{profile}:{kind}"
    targets = precise_targets(spec, params)
    for item in targets["resources"]:
        return item["id"]
    for item in targets["paths"]:
        return item["path"]
    # Medium-risk local effects (e.g. ip reserve) confirm on the precise scope
    # value (the reserved IP) rather than an abstract command name.
    for preferred in ("ip", "lease_id"):
        for item in targets["scopes"]:
            if item["kind"] == preferred:
                return item["value"]
    return spec.path
