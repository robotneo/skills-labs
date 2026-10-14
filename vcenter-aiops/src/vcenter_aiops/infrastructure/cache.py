"""Explicit, bounded inventory snapshots in the existing transactional Store."""
import hashlib
import json
import math
import time

from ..domain.models import fail
from .store import canonical


KINDS = ("vm", "host", "cluster", "datastore")
SCHEMA_VERSION = 1
TTL_SECONDS = 300
MAX_ITEMS = 1000
MAX_BYTES = 1_000_000


def profile_fingerprint(config):
    identity = {key: config.get(key) for key in ("host", "port", "user", "verify_tls", "ca_file")}
    return hashlib.sha256(canonical(identity).encode("utf-8")).hexdigest()


def _primitives(value, depth=0):
    if depth > 12:
        return False
    if value is None:
        return True
    # bool before int (bool subclasses int); isinstance also accepts pyVmomi's
    # VmomiSupport.long used for 64-bit inventory fields on real vCenter.
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return all(_primitives(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return all(type(key) is str and _primitives(item, depth + 1) for key, item in value.items())
    return False


class CacheStore:
    def __init__(self, store):
        self.store = store
        self.db = store.db
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS inventory_cache_generations (
                profile TEXT NOT NULL, kind TEXT NOT NULL, generation INTEGER NOT NULL,
                PRIMARY KEY(profile, kind));
            CREATE TABLE IF NOT EXISTS inventory_cache (
                profile TEXT NOT NULL, instance_uuid TEXT NOT NULL, kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(profile, instance_uuid, kind));
        """)

    @staticmethod
    def _scope(profile, kind):
        if type(profile) is not str or not profile or type(kind) is not str or kind not in KINDS:
            fail("cache_scope_invalid", "缓存须使用明确 Profile 和支持的资产类型", 2)

    def _advance(self, profile, kind):
        row = self.db.execute("SELECT generation FROM inventory_cache_generations WHERE profile=? AND kind=?",
                              (profile, kind)).fetchone()
        generation = row[0] + 1 if row else 1
        self.db.execute("INSERT INTO inventory_cache_generations VALUES(?,?,?) "
                        "ON CONFLICT(profile,kind) DO UPDATE SET generation=excluded.generation",
                        (profile, kind, generation))
        return generation

    def begin(self, profile, kind):
        self._scope(profile, kind)
        with self.store.transaction():
            return self._advance(profile, kind)

    @staticmethod
    def _encode(profile, instance_uuid, kind, config, data, collected_at):
        if type(instance_uuid) is not str or not instance_uuid or len(instance_uuid) > 128:
            fail("cache_payload_invalid", "服务端 instance UUID 无效", 4)
        if (type(data) is not dict or set(data) != {"items", "truncated"}
                or type(data["items"]) is not list or len(data["items"]) > MAX_ITEMS
                or type(data["truncated"]) is not bool or not _primitives(data)):
            fail("cache_payload_invalid", "资产快照不是有界原始数据", 4)
        if any(type(row) is not dict or type(row.get("id")) is not str or not row["id"]
               or row.get("kind") != kind for row in data["items"]):
            fail("cache_payload_invalid", "资产快照包含无效对象身份", 4)
        envelope = {"schema_version": SCHEMA_VERSION, "profile": profile,
                    "instance_uuid": instance_uuid, "kind": kind,
                    "profile_fingerprint": profile_fingerprint(config),
                    "collected_at": collected_at, "source": "live_inventory",
                    "data": data}
        encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_BYTES:
            fail("cache_payload_too_large", "资产快照超过本地缓存容量限制", 4)
        return encoded

    def publish(self, profile, instance_uuid, kind, generation, config, data, collected_at=None):
        self._scope(profile, kind)
        collected_at = time.time() if collected_at is None else collected_at
        encoded = self._encode(profile, instance_uuid, kind, config, data, collected_at)
        with self.store.transaction():
            row = self.db.execute("SELECT generation FROM inventory_cache_generations WHERE profile=? AND kind=?",
                                  (profile, kind)).fetchone()
            if row is None or row[0] != generation:
                return False
            self.db.execute("INSERT INTO inventory_cache VALUES(?,?,?,?) "
                            "ON CONFLICT(profile,instance_uuid,kind) DO UPDATE SET payload=excluded.payload",
                            (profile, instance_uuid, kind, encoded))
        age = time.time() - collected_at
        snapshot = {"instance_uuid": instance_uuid, "kind": kind,
                    "current_server_unverified": True,
                    "state": "expired" if not 0 <= age <= TTL_SECONDS else "partial" if data["truncated"] else "fresh",
                    "age_fresh": 0 <= age <= TTL_SECONDS, "profile_matches": True,
                    "collected_at": collected_at, "source": "live_inventory",
                    "count": len(data["items"]), "truncated": data["truncated"], "ttl_seconds": TTL_SECONDS}
        return {"generation": generation, "encoded": encoded, "snapshot": snapshot}

    def is_current(self, profile, instance_uuid, kind, publication):
        self._scope(profile, kind)
        with self.store.transaction():
            generation = self.db.execute(
                "SELECT generation FROM inventory_cache_generations WHERE profile=? AND kind=?",
                (profile, kind)).fetchone()
            row = self.db.execute(
                "SELECT payload FROM inventory_cache WHERE profile=? AND instance_uuid=? AND kind=?",
                (profile, instance_uuid, kind)).fetchone()
            return (generation is not None and generation[0] == publication["generation"]
                    and row is not None and row[0] == publication["encoded"])

    def status(self, profile, kind, config, now=None):
        self._scope(profile, kind)
        now = time.time() if now is None else now
        rows = self.db.execute("SELECT instance_uuid,payload FROM inventory_cache "
                               "WHERE profile=? AND kind=? ORDER BY instance_uuid", (profile, kind))
        snapshots = []
        for row in rows:
            meta = {"instance_uuid": row["instance_uuid"], "kind": kind,
                    "current_server_unverified": True}
            raw = row["payload"]
            try:
                if len(raw.encode("utf-8")) > MAX_BYTES:
                    raise ValueError("oversize")
                payload = json.loads(raw)
                data = payload["data"]
                if (type(payload) is not dict or payload.get("schema_version") != SCHEMA_VERSION
                        or payload.get("profile") != profile or payload.get("kind") != kind
                        or payload.get("instance_uuid") != row["instance_uuid"]
                        or payload.get("source") != "live_inventory"
                        or type(payload.get("profile_fingerprint")) is not str
                        or type(payload.get("collected_at")) not in (int, float)
                        or not math.isfinite(payload["collected_at"])
                        or type(data) is not dict or set(data) != {"items", "truncated"}
                        or type(data["items"]) is not list or len(data["items"]) > MAX_ITEMS
                        or type(data["truncated"]) is not bool or not _primitives(data)
                        or any(type(item) is not dict or item.get("kind") != kind
                               or type(item.get("id")) is not str or not item["id"] for item in data["items"])):
                    raise ValueError("unsupported")
            except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
                snapshots.append({**meta, "state": "corrupt", "age_fresh": False,
                                  "profile_matches": False})
                continue
            age = now - payload["collected_at"]
            age_fresh = 0 <= age <= TTL_SECONDS
            profile_matches = payload["profile_fingerprint"] == profile_fingerprint(config)
            state = ("profile_changed" if not profile_matches else "expired" if not age_fresh
                     else "partial" if data["truncated"] else "fresh")
            snapshots.append({**meta, "state": state, "age_fresh": age_fresh,
                              "profile_matches": profile_matches,
                              "collected_at": payload["collected_at"], "source": payload["source"],
                              "count": len(data["items"]), "truncated": data["truncated"],
                              "ttl_seconds": TTL_SECONDS})
        return {"profile": profile, "kind": kind, "state": "present" if snapshots else "missing",
                "present": bool(snapshots), "snapshots": snapshots,
                "scope": "all_recorded_servers_for_profile_and_kind"}

    def invalidate(self, profile, kind):
        self._scope(profile, kind)
        with self.store.transaction():
            self._advance(profile, kind)
            return self.db.execute("DELETE FROM inventory_cache WHERE profile=? AND kind=?",
                                   (profile, kind)).rowcount
