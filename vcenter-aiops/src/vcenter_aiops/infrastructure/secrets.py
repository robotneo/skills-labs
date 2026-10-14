"""Authenticated local vault. No plaintext persistence or master-key generation.

The POSIX backend anchors every child operation to a private directory descriptor.
Windows deliberately fails closed pending a native secure-storage backend.
"""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import re
import uuid

from ..domain.models import fail
from .locking import exclusive, open_private

MAX_SECRET_BYTES = 4096
MAX_VAULT_BYTES = 8 * 1024 * 1024


def validate_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        fail("secret_name_invalid", "密钥名称须为 1–64 个字母、数字、下划线或连字符", 2)


def valid_value(value):
    try:
        return isinstance(value, str) and 0 < len(value.encode("utf-8")) <= MAX_SECRET_BYTES
    except UnicodeError:
        return False


def validate_value(value):
    if not valid_value(value):
        fail("secret_value_invalid", "秘密值须为非空 UTF-8 文本，最多 4096 字节", 2)


def _cipher():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        fail("dependency_missing", "密钥库需要安装 secrets 可选依赖 cryptography", 3)
    key = os.environ.get("VCENTER_AIOPS_MASTER_KEY")
    if not key:
        fail("secret_key_missing", "请独立设置 VCENTER_AIOPS_MASTER_KEY；不会自动生成或保存主密钥", 3)
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}=", key) or base64.urlsafe_b64encode(base64.urlsafe_b64decode(key)).decode() != key:
            raise ValueError
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError):
        fail("secret_key_invalid", "主密钥须为 32 字节的 URL-safe base64 编码", 3)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError):
        fail("secret_storage_invalid", "密钥库结构无效；原库未覆盖", 3)


def _object(value, fields):
    return isinstance(value, dict) and set(value) == fields


def _utc(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0
    except ValueError:
        return False


def _validate_inner(value):
    valid = _object(value, {"schema_version", "secrets"}) and type(value["schema_version"]) is int and value["schema_version"] == 1 and isinstance(value["secrets"], dict)
    if valid:
        for name, entry in value["secrets"].items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) or not _object(entry, {"value", "revision", "created_at", "updated_at"}):
                valid = False
                break
            if not valid_value(entry["value"]) or type(entry["revision"]) is not int or entry["revision"] < 1 or not _utc(entry["created_at"]) or not _utc(entry["updated_at"]):
                valid = False
                break
    if not valid:
        fail("secret_storage_invalid", "密钥库结构无效；原库未覆盖", 3)
    return value


@contextmanager
def _private_directory(home):
    """Only this backend owns platform filesystem semantics; never resolve links."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        fail("secret_storage_unsupported", "此平台尚无安全密钥库存储后端", 3)
    try:
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                fail("secret_storage_unsafe", "密钥库目录必须仅当前用户可访问", 3)
            yield fd
        finally:
            os.close(fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            fail("secret_storage_unsafe", "密钥库目录或文件不能为符号链接或特殊文件", 3)
        fail("secret_storage_io", "密钥库无法安全读写；请检查目录及权限", 3)


def _metadata(name, entry):
    return {"name": name, **{field: entry[field] for field in ("revision", "created_at", "updated_at")}}


class SecretVault:
    def __init__(self, home):
        self.home = Path(home)

    @contextmanager
    def _transaction(self):
        cipher = _cipher()
        with _private_directory(self.home) as directory:
            with exclusive(Path("secrets.lock"), secure=True, dir_fd=directory):
                yield directory, cipher, self._load(directory, cipher)

    def _load(self, directory, cipher):
        try:
            fd = open_private("secrets.json", os.O_RDONLY, dir_fd=directory)
        except FileNotFoundError:
            return {"schema_version": 1, "secrets": {}}
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read(MAX_VAULT_BYTES + 1)
        if len(raw) > MAX_VAULT_BYTES:
            fail("secret_storage_invalid", "密钥库超过 8 MiB 上限", 3)
        envelope = _json(raw)
        if not _object(envelope, {"schema_version", "ciphertext"}) or type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1 or not isinstance(envelope["ciphertext"], str):
            fail("secret_storage_invalid", "密钥库结构无效；原库未覆盖", 3)
        from cryptography.fernet import InvalidToken
        try:
            token = envelope["ciphertext"].encode("ascii")
            # Fernet's base64 decoder accepts ignored trailing junk; our file format does not.
            if base64.urlsafe_b64encode(base64.b64decode(token, altchars=b"-_", validate=True)) != token:
                raise ValueError
            plaintext = cipher.decrypt(token)
        except (InvalidToken, UnicodeError, ValueError):
            fail("secret_authentication_failed", "主密钥不匹配或密文损坏；原库未覆盖", 3)
        return _validate_inner(_json(plaintext))

    def _save(self, directory, cipher, value):
        encrypted = cipher.encrypt(json.dumps(value, ensure_ascii=False).encode("utf-8")).decode("ascii")
        raw = json.dumps({"schema_version": 1, "ciphertext": encrypted}).encode("ascii")
        if len(raw) > MAX_VAULT_BYTES:
            fail("secret_storage_full", "密钥库超过 8 MiB 上限；原库未覆盖", 3)
        temporary = ".secrets-" + uuid.uuid4().hex + ".tmp"
        created = False
        try:
            fd = open_private(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, dir_fd=directory)
            created = True
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, "secrets.json", src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            if created:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass

    def list(self):
        with self._transaction() as (_, _, value):
            return [_metadata(name, entry) for name, entry in sorted(value["secrets"].items())]

    def resolve(self, name):
        validate_name(name)
        with self._transaction() as (_, _, value):
            if name not in value["secrets"]:
                fail("secret_not_found", "精确名称的秘密不存在", 3)
            return value["secrets"][name]["value"]

    def set(self, name, secret):
        return self._write(name, secret, replace=False)

    def rotate(self, name, secret):
        return self._write(name, secret, replace=True)

    def _write(self, name, secret, replace):
        validate_name(name)
        validate_value(secret)
        with self._transaction() as (directory, cipher, value):
            existing = value["secrets"].get(name)
            if replace and existing is None:
                fail("secret_not_found", "精确名称的秘密不存在", 3)
            if not replace and existing is not None:
                fail("secret_exists", "秘密已存在；使用 rotate 替换精确名称的值", 2)
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            entry = {"value": secret, "revision": existing["revision"] + 1 if existing else 1,
                     "created_at": existing["created_at"] if existing else now, "updated_at": now}
            value["secrets"][name] = entry
            self._save(directory, cipher, value)
            return _metadata(name, entry)

    def delete(self, name):
        validate_name(name)
        with self._transaction() as (directory, cipher, value):
            if name not in value["secrets"]:
                fail("secret_not_found", "精确名称的秘密不存在", 3)
            del value["secrets"][name]
            self._save(directory, cipher, value)
