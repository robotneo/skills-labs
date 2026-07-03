"""
Module: scripts.secret_manager
Description: 密码加密管理。Fernet 对称加密存储敏感凭据，主密钥从环境变量或文件加载。
Author: 运枢
Date: 2026-05-22
Version: 1.3.0

设计要点：
- 替代 .env 明文密码：加密后存储在 data/secrets.json
- 主密钥来源优先级：VC_MASTER_KEY 环境变量 > data/.master_key 文件 > 自动生成
- 加密密码绝不落盘明文；运行时解密仅在内存中
- 提供 encrypt / decrypt / rotate_key / migrate_from_env 四个核心操作
- 向后兼容：未迁移时仍可读 .env 明文
"""

import os
import json
import base64
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent.parent
SECRETS_FILE = SKILL_DIR / "data" / "secrets.json"
MASTER_KEY_FILE = SKILL_DIR / "data" / ".master_key"
SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)

# 明文 .env 路径（用于迁移）
ENV_FILE = SKILL_DIR / ".env"


# ============================================================
# 主密钥管理
# ============================================================

def _generate_master_key() -> bytes:
    """生成新的 Fernet 主密钥。"""
    return Fernet.generate_key()


def _derive_key_from_password(password: str, salt: Optional[bytes] = None) -> tuple:
    """
    从密码派生 Fernet 密钥（PBKDF2 + SHA256）。
    返回 (key_bytes, salt_base64)。
    """
    if salt is None:
        salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key, base64.urlsafe_b64encode(salt).decode()


def load_master_key(auto_create: bool = True) -> bytes:
    """
    加载主密钥。

    优先级：
    1. VC_MASTER_KEY 环境变量（原始 Fernet key 或密码）
    2. data/.master_key 文件
    3. 自动生成并保存（仅 auto_create=True 时）
    """
    # 1) 环境变量
    env_key = os.environ.get("VC_MASTER_KEY", "").strip()
    if env_key:
        # 如果是合法 Fernet key（44 字符 base64），直接用
        try:
            Fernet(env_key.encode() if isinstance(env_key, str) else env_key)
            return env_key.encode() if isinstance(env_key, str) else env_key
        except Exception:
            # 当作密码，派生密钥
            key, _ = _derive_key_from_password(env_key)
            logger.info("从 VC_MASTER_KEY 环境变量派生密钥")
            return key

    # 2) 文件
    if MASTER_KEY_FILE.exists():
        key = MASTER_KEY_FILE.read_bytes().strip()
        try:
            Fernet(key)
            return key
        except Exception:
            pass

    # 3) 自动生成
    if auto_create:
        key = _generate_master_key()
        MASTER_KEY_FILE.write_bytes(key)
        MASTER_KEY_FILE.chmod(0o600)
        logger.info("🔑 自动生成主密钥并保存到 data/.master_key（chmod 600）")
        return key

    raise RuntimeError("未找到主密钥。请设置 VC_MASTER_KEY 环境变量或检查 data/.master_key")


# ============================================================
# 加密/解密
# ============================================================

def _get_fernet() -> Fernet:
    return Fernet(load_master_key())


def encrypt_value(plaintext: str) -> str:
    """加密明文，返回 base64 编码的密文。"""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """解密密文，返回明文字符串。"""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()


# ============================================================
# secrets.json 管理
# ============================================================

def _load_secrets() -> Dict[str, Any]:
    if not SECRETS_FILE.exists():
        return {"secrets": {}, "metadata": {"version": "1.3.0", "created_at": None}}
    try:
        return json.loads(SECRETS_FILE.read_text())
    except Exception:
        return {"secrets": {}, "metadata": {"version": "1.3.0"}}


def _save_secrets(data: Dict[str, Any]) -> None:
    SECRETS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    SECRETS_FILE.chmod(0o600)
    logger.info(f"🔐 secrets.json 已更新（chmod 600）")


def set_secret(key: str, plaintext: str, description: str = "") -> Dict[str, Any]:
    """
    加密并存储一个秘密值。

    :param key: 键名（如 VCENTER_PASSWORD、DB_PASSWORD）
    :param plaintext: 明文值
    :param description: 描述（可选）
    """
    ciphertext = encrypt_value(plaintext)
    data = _load_secrets()
    data["secrets"][key] = {
        "ciphertext": ciphertext,
        "description": description,
        "key_length": len(plaintext),
    }
    _save_secrets(data)
    logger.info(f"🔐 已加密存储: {key}")
    return {"key": key, "stored": True, "description": description}


def get_secret(key: str) -> Optional[str]:
    """解密并返回指定键的明文值。键不存在返回 None。"""
    data = _load_secrets()
    entry = data.get("secrets", {}).get(key)
    if not entry:
        return None
    try:
        return decrypt_value(entry["ciphertext"])
    except Exception as e:
        logger.error(f"解密 {key} 失败（可能主密钥已变更）: {e}")
        raise


def delete_secret(key: str) -> bool:
    data = _load_secrets()
    if key in data.get("secrets", {}):
        del data["secrets"][key]
        _save_secrets(data)
        logger.info(f"🗑️ 已删除秘密: {key}")
        return True
    return False


def list_secret_keys() -> list:
    """列出所有存储的键名（不返回明文）。"""
    data = _load_secrets()
    return [
        {"key": k, "description": v.get("description", ""), "key_length": v.get("key_length", 0)}
        for k, v in data.get("secrets", {}).items()
    ]


# ============================================================
# 迁移：从 .env 明文迁移到加密存储
# ============================================================

def migrate_from_env(dry_run: bool = False) -> Dict[str, Any]:
    """
    扫描 .env 文件中的明文密码，加密后存入 secrets.json。
    默认只迁移包含 PASSWORD / SECRET / TOKEN / KEY 的行。
    """
    if not ENV_FILE.exists():
        return {"migrated": 0, "message": ".env 文件不存在，无需迁移"}

    # 定义需要迁移的关键词
    secret_keywords = ("PASSWORD", "SECRET", "TOKEN", "KEY", "PASSWD", "CREDENTIAL")

    migrated = []
    skipped = []
    lines_to_keep = []

    for line in ENV_FILE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            lines_to_keep.append(line)
            continue

        if "=" not in stripped:
            lines_to_keep.append(line)
            continue

        k, v = stripped.split("=", 1)
        k = k.strip()
        v = v.strip()

        if any(kw in k.upper() for kw in secret_keywords):
            migrated.append(k)
            if not dry_run:
                set_secret(k, v, description=f"从 .env 迁移 ({k})")
                # .env 中替换为引用标记
                lines_to_keep.append(f"# [已迁移到 secrets.json] {k}=***")
            else:
                lines_to_keep.append(line)
        else:
            lines_to_keep.append(line)
            skipped.append(k)

    if not dry_run and migrated:
        # 备份原 .env
        backup = ENV_FILE.with_suffix(".env.bak")
        ENV_FILE.rename(backup)
        # 写入新 .env（去掉已迁移的明文）
        ENV_FILE.write_text("\n".join(lines_to_keep) + "\n")
        logger.info(f"📦 .env 已备份到 {backup}，明文密码已清除")

    return {
        "migrated": migrated,
        "skipped": skipped,
        "dry_run": dry_run,
        "message": f"{'[DRY-RUN] ' if dry_run else ''}迁移 {len(migrated)} 个秘密，跳过 {len(skipped)} 个非秘密键",
    }


# ============================================================
# 密钥轮换
# ============================================================

def rotate_key() -> Dict[str, Any]:
    """
    轮换主密钥：用旧密钥解密所有秘密，生成新密钥，重新加密。
    """
    old_key = load_master_key(auto_create=False)
    old_fernet = Fernet(old_key)

    # 读取当前密文
    data = _load_secrets()
    re_encrypted = 0
    failed = []

    for key, entry in data.get("secrets", {}).items():
        try:
            plaintext = old_fernet.decrypt(entry["ciphertext"].encode()).decode()
            entry["ciphertext"] = encrypt_value(plaintext)
            re_encrypted += 1
        except Exception as e:
            failed.append({"key": key, "error": str(e)})

    if failed:
        logger.error(f"密钥轮换失败 {len(failed)} 项: {failed}")
        raise RuntimeError(f"密钥轮换部分失败: {failed}")

    _save_secrets(data)

    # 更新主密钥文件
    new_key = _generate_master_key()
    MASTER_KEY_FILE.write_bytes(new_key)
    MASTER_KEY_FILE.chmod(0o600)
    logger.info(f"🔑 主密钥已轮换，重新加密 {re_encrypted} 项")

    return {"re_encrypted": re_encrypted, "message": "密钥轮换完成"}


# ============================================================
# 兼容层：handler 调用 get_secret 代替 .env 读取
# ============================================================

def resolve_password(key: str, fallback_env: str = "") -> str:
    """
    解析密码：优先 secrets.json 加密存储 → 环境变量 → 明文 .env。
    与现有 handler.resolve_connection 兼容。
    """
    # 1) 加密存储
    val = get_secret(key)
    if val:
        return val

    # 2) 直接环境变量
    env_val = os.environ.get(key, "").strip()
    if env_val:
        return env_val

    # 3) fallback 环境变量名
    if fallback_env:
        fb = os.environ.get(fallback_env, "").strip()
        if fb:
            return fb

    return ""


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="密码加密管理")
    sub = parser.add_subparsers(dest="cmd")

    p_set = sub.add_parser("set", help="加密存储一个秘密")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument("--desc", default="")

    p_get = sub.add_parser("get", help="解密获取秘密（⚠️ 明文输出）")
    p_get.add_argument("key")

    p_del = sub.add_parser("delete", help="删除秘密")
    p_del.add_argument("key")

    sub.add_parser("list", help="列出已存储键名")

    p_migrate = sub.add_parser("migrate", help="从 .env 迁移明文密码")
    p_migrate.add_argument("--dry-run", action="store_true")

    sub.add_parser("rotate", help="轮换主密钥")

    args = parser.parse_args()

    if args.cmd == "set":
        set_secret(args.key, args.value, description=args.desc)
        print(f"✅ 已加密存储: {args.key}")
    elif args.cmd == "get":
        val = get_secret(args.key)
        print(val if val else "⚠️ 未找到该键")
    elif args.cmd == "delete":
        ok = delete_secret(args.key)
        print(f"{'✅ 已删除' if ok else '⚠️ 未找到'}: {args.key}")
    elif args.cmd == "list":
        keys = list_secret_keys()
        if not keys:
            print("📭 暂无加密存储的秘密")
        for k in keys:
            print(f"  🔑 {k['key']:30s} | {k['description'] or '-'} | 长度={k['key_length']}")
    elif args.cmd == "migrate":
        result = migrate_from_env(dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == "rotate":
        result = rotate_key()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
