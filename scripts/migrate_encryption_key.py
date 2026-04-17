#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
迁移脚本：用旧密钥解密数据库中的密钥，再用新密钥重新加密。

使用场景：
  - APIPOOL_ENCRYPTION_KEY 被更改或丢失
  - 数据库中的密文无法被当前配置的密钥解密
  - 需要将所有 Key 迁移到新的加密密钥

用法：
  # 方式1：用旧密钥迁移（推荐）
  python scripts/migrate_encryption_key.py --old-key <旧Fernet密钥Base64>

  # 方式2：先预览不执行
  python scripts/migrate_encryption_key.py --old-key <旧密钥> --dry-run

示例：
  python scripts/migrate_encryption_key.py --old-key O66x_Bxxkww_fGp8xepRgYXSYf_cubpVb2YW_X9FMSM=
"""

import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from cryptography.fernet import Fernet, InvalidToken


def get_db_session(db_url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(db_url)
    return sessionmaker(bind=engine)()


def migrate_with_old_key(old_key_b64: str, db_url: str, dry_run: bool = False):
    """使用旧密钥解密后，再用当前 .env 中的新密钥重新加密所有 API Key。"""
    from apipool_server.security import KeyEncryption
    from apipool_server.models.api_key_entry import ApiKeyEntry

    print(f"[*] 验证旧密钥格式...")
    try:
        old_fernet = Fernet(old_key_b64.encode())
        _test = old_fernet.encrypt(b"test")
        old_fernet.decrypt(_test)
    except Exception as e:
        print(f"[ERROR] 旧密钥无效: {e}")
        sys.exit(1)

    db = get_db_session(db_url)
    entries = db.query(ApiKeyEntry).filter(ApiKeyEntry.is_archived == False).all()
    total = len(entries)
    print(f"[*] 找到 {total} 个非归档的 API Key")

    success = 0
    failed = 0
    for entry in entries:
        try:
            # 用旧密钥解密
            raw_key = old_fernet.decrypt(entry.encrypted_key.encode("utf-8")).decode("utf-8")
            if not dry_run:
                # 用新密钥（当前 .env 配置）重新加密
                entry.encrypted_key = KeyEncryption.encrypt(raw_key)
            print(f"  [OK] {entry.identifier}")
            success += 1
        except InvalidToken:
            print(f"  [FAIL] {entry.identifier} — 无法用旧密钥解密（可能已被新密钥加密过）")
            failed += 1
        except Exception as e:
            print(f"  [FAIL] {entry.identifier} — {e}")
            failed += 1

    if not dry_run and success > 0:
        db.commit()
        print(f"\n[SUCCESS] 成功迁移 {success} 个 Key，失败 {failed} 个")
    elif dry_run:
        print(f"\n[DRY RUN] 将迁移 {success} 个 Key，失败 {failed} 个（未实际修改数据库）")
    else:
        print(f"\n[WARN] 没有需要迁移的 Key")

    db.close()


def rebuild_from_plaintext(keys_file: Path, db_url: str, dry_run: bool = False):
    """当旧密钥已完全丢失时，用明文 JSON 文件重建所有密钥。

    keys.json 格式:
    [
      {"identifier": "my-key-1", "raw_key": "sk-actual-secret-value"},
      {"identifier": "my-key-2", "raw_key": "sk-another-secret"}
    ]
    """
    from apipool_server.security import KeyEncryption
    from apipool_server.models.api_key_entry import ApiKeyEntry

    if not keys_file.exists():
        print(f"[ERROR] 文件不存在: {keys_file}")
        sys.exit(1)

    with open(keys_file, "r", encoding="utf-8") as f:
        key_list = json.load(f)

    key_map = {item["identifier"]: item["raw_key"] for item in key_list}
    print(f"[*] 从文件加载了 {len(key_map)} 个明文 Key")

    db = get_db_session(db_url)
    entries = db.query(ApiKeyEntry).filter(ApiKeyEntry.is_archived == False).all()

    success = 0
    not_found = 0
    for entry in entries:
        if entry.identifier in key_map:
            if not dry_run:
                entry.encrypted_key = KeyEncryption.encrypt(key_map[entry.identifier])
            print(f"  [OK] {entry.identifier} — 已重新加密")
            success += 1
        else:
            print(f"  [SKIP] {entry.identifier} — 文件中未找到明文")
            not_found += 1

    missing_in_db = set(key_map.keys()) - {e.identifier for e in entries}
    for ident in sorted(missing_in_db):
        print(f"  [WARN] {ident} — 文件中存在但数据库中未找到")

    if not dry_run and success > 0:
        db.commit()
        print(f"\n[SUCCESS] 成功重建 {success} 个 Key，跳过 {not_found} 个")
    elif dry_run:
        print(f"\n[DRY RUN] 将重建 {success} 个 Key，跳过 {not_found} 个")

    db.close()


def main():
    parser = argparse.ArgumentParser(
        description="迁移 API Key 加密密钥 — 解决 InvalidToken / Signature did not match 错误",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 用旧 Fernet 密钥迁移所有数据到当前 .env 中配置的新密钥
  python scripts/migrate_encryption_key.py --old-key <旧的Base64密钥>

  # 先预览效果
  python scripts/migrate_encryption_key.py --old-key <旧密钥> --dry-run

  # 如果旧密钥已丢失，用明文文件重建（需自行准备 keys.json）
  python scripts/migrate_encryption_key.py --rebuild --keys-file keys.json
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--old-key",
        type=str,
        help="旧的 Fernet 加密密钥 (Base64)，即当初加密数据时使用的 APIPOOL_ENCRYPTION_KEY 值",
    )
    group.add_argument(
        "--rebuild",
        action="store_true",
        help="从明文 JSON 文件重建密钥（用于旧密钥彻底丢失的场景）",
    )

    parser.add_argument("--keys-file", type=Path, default=Path("keys.json"),
                        help="明文 Key 文件路径（配合 --rebuild 使用），默认: keys.json")
    parser.add_argument("--db-url", type=str, default=None,
                        help="数据库连接 URL，默认读取 .env 中的 DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅预览，不实际修改数据库")

    args = parser.parse_args()

    # 确定 DB URL
    if args.db_url:
        db_url = args.db_url
    else:
        from apipool_server.config import get_settings
        db_url = get_settings().DATABASE_URL
    print(f"[*] 数据库: {db_url}")

    if args.old_key:
        migrate_with_old_key(args.old_key, db_url, args.dry_run)
    elif args.rebuild:
        rebuild_from_plaintext(args.keys_file, db_url, args.dry_run)


if __name__ == "__main__":
    main()
