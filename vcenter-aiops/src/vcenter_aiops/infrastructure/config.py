"""Profile configuration without plaintext credentials or import side effects."""
import json
import os
import re
import tempfile
from pathlib import Path

from ..domain.models import fail
from .paths import ensure_private
from .locking import exclusive
from .credentials import validate_reference


class Profiles:
    def __init__(self, home: Path):
        self.path = home / "config.yaml"

    def load(self):
        if not self.path.exists():
            return {"schema_version": 1, "profiles": {}}
        try:
            import yaml
        except ImportError:
            fail("dependency_missing", "读取配置需要 PyYAML", 3)
        try:
            value = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError, yaml.YAMLError):
            fail("config_invalid", "配置文件不可读取", 3)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            fail("config_invalid", "不支持的配置结构", 3)
        profiles = value.get("profiles")
        if not isinstance(profiles, dict):
            fail("config_invalid", "profiles 必须为对象", 3)
        for name, profile in profiles.items():
            self.validate(name, profile)
        return value

    @staticmethod
    def validate(name, profile):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            fail("profile_invalid", "Profile 名称只能包含字母、数字、下划线、连字符", 2)
        allowed = {"host", "user", "password_ref", "port", "verify_tls", "ca_file"}
        if not isinstance(profile, dict) or set(profile) - allowed:
            fail("profile_invalid", "配置含未知字段；不允许存储明文凭据", 2)
        for key in ("host", "user", "password_ref"):
            if not isinstance(profile.get(key), str) or not profile[key].strip():
                fail("profile_invalid", "host/user/password_ref 不能为空", 2)
        validate_reference(profile["password_ref"])
        port = profile.get("port", 443)
        if type(port) is not int or not 1 <= port <= 65535:
            fail("profile_invalid", "端口必须为 1–65535", 2)
        if type(profile.get("verify_tls", True)) is not bool:
            fail("profile_invalid", "verify_tls 必须为布尔值", 2)
        if "ca_file" in profile and profile["ca_file"] is not None and not isinstance(profile["ca_file"], str):
            fail("profile_invalid", "ca_file 必须为路径", 2)

    def get(self, name):
        if not name:
            fail("profile_required", "请显式指定 --profile", 3)
        value = self.load()["profiles"].get(name)
        if value is None:
            fail("profile_not_found", "指定 Profile 不存在", 3)
        return value

    def save(self, value):
        # Callers hold the profile lock through read-modify-replace.
        ensure_private(self.path.parent)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             delete=False) as handle:
                temporary = handle.name
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def put(self, name, profile, replace=False):
        self.validate(name, profile)
        with exclusive(self.path.with_suffix(".lock")):
            value = self.load()
            exists = name in value["profiles"]
            if exists and not replace:
                fail("profile_exists", "Profile 已存在", 2)
            if replace and not exists:
                fail("profile_not_found", "Profile 不存在", 3)
            value["profiles"][name] = profile
            self.save(value)

    def update(self, name, changes):
        with exclusive(self.path.with_suffix(".lock")):
            value = self.load()
            if name not in value["profiles"]:
                fail("profile_not_found", "Profile 不存在", 3)
            merged = {**value["profiles"][name], **changes}
            self.validate(name, merged)
            value["profiles"][name] = merged
            self.save(value)
            return merged

    def delete(self, name):
        with exclusive(self.path.with_suffix(".lock")):
            value = self.load()
            if name not in value["profiles"]:
                fail("profile_not_found", "Profile 不存在", 3)
            del value["profiles"][name]
            self.save(value)
