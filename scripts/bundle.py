#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bundle.py——starfish 资源 bundle 打包器（规范锁死，单一实现）。

  python bundle.py pack --src <目录> --out <目录> --key <64hex|@文件> [--prefix <前缀>] [--magic SFXE1]

规范（与 starfish-io 逐字节一致——io 层是唯一消费方，公式由它锚定）：
  逻辑路径 rel = [--prefix + "/"] + 相对 src 的 POSIX 路径
  文件名 = SHA-256(rel + key_hex)[:32].hex + ".sfx"        ← io::sfx_hash 同款
  内容   = magic(5) | nonce(12) | ChaCha20-Poly1305 密文+tag
           AAD = "starfish-asset-v1"                        ← io::unwrap_envelope 同款
遍历排除：__pycache__、点开头文件/目录。out 已存在 = 拒绝（防覆盖）。
产物 = 扁平 .sfx 文件集（零目录结构、零原始名暴露）。

副本纪律：pygamest-dev/scripts 与 pygamest-runtime/scripts 两份必须
逐字节一致（cmp 校验）；改规范 = 双份同改 + 对齐 io 层。
"""
import argparse
import fnmatch
import hashlib
import os
import shutil
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

DOMAIN_AAD = b"starfish-asset-v1"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def sfx_name(logical: str, key_hex: str) -> str:
    """逻辑路径 + 密钥 hex → 确定性哈希文件名（io::sfx_hash 同公式）"""
    digest = hashlib.sha256((logical + key_hex).encode("utf-8")).hexdigest()
    return digest[:32] + ".sfx"


def parse_key(spec: str) -> str:
    """64 位 hex 直传，或 @文件 读入"""
    key_hex = Path(spec[1:]).read_text(encoding="ascii").strip() if spec.startswith("@") else spec.strip()
    if len(key_hex) != 64:
        sys.exit("[FAIL] --key 须为 64 位 hex 或 @密钥文件（32 字节）")
    return key_hex


def ignored(rel_posix: str, patterns) -> bool:
    """rel 路径（POSIX 形）或其末段命中任一 glob = 剔除"""
    name = rel_posix.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(rel_posix, p) or fnmatch.fnmatch(name, p) for p in patterns)


def walk(src: Path, extra_ignores=()):
    """递归产出文件（排除 __pycache__ / 点开头 / --ignore glob）"""
    for root, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        for f in sorted(files):
            if f.startswith("."):
                continue
            rel = (Path(root) / f).relative_to(src).as_posix()
            if ignored(rel, extra_ignores):
                continue
            yield Path(root) / f


def cmd_pack(args) -> int:
    src, out = Path(args.src).resolve(), Path(args.out)
    if not src.is_dir():
        sys.exit(f"[FAIL] --src 不是目录: {src}")
    if out.exists():
        sys.exit(f"[FAIL] --out 已存在（防覆盖）: {out}")
    key_hex = parse_key(args.key)
    key = bytes.fromhex(key_hex)
    magic = args.magic.encode("ascii")
    if len(magic) != 5:
        sys.exit("[FAIL] --magic 须为 5 字符")
    aead = ChaCha20Poly1305(key)
    # 明文豁免扩展（--plain-ext，如 mp4）：原路径原样拷贝、零加密零哈希
    # 名——大媒体资产直供原生解码器（MF/MediaCodec 要 seekable 文件路径；
    # 全量解密喂解码器对大视频不合理，2026-11-10 用户定约方案 A）
    plain_exts = tuple(e.lower().lstrip(".") for e in (args.plain_ext or []))

    out.mkdir(parents=True)
    n = total = skipped = plain_n = 0
    for f in walk(src, args.ignore):
        rel = f.relative_to(src).as_posix()
        logical = f"{args.prefix}/{rel}" if args.prefix else rel
        if plain_exts and f.suffix.lower().lstrip(".") in plain_exts:
            dst = out / Path(logical)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            plain_n += 1
            print(f"  {logical} → {dst.relative_to(out).as_posix()}（明文豁免）")
            continue
        data = f.read_bytes()
        nonce = os.urandom(12)
        env = magic + nonce + aead.encrypt(nonce, data, DOMAIN_AAD)
        # 目录结构保留（2026-11-03 用户定约）：哈希文件写在其逻辑路径的
        # 原目录位（assets/<hash>.sfx）——目录形状镜像源侧，叶子名不可读
        dst = out / Path(logical).parent / sfx_name(logical, key_hex)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(env)
        n += 1
        total += len(env)
        print(f"  {logical} → {dst.relative_to(out).as_posix()}（{len(data)}B）")
    if args.ignore:
        skipped = sum(1 for root, _, files in os.walk(src) for f in files
                      if ignored(os.path.relpath(os.path.join(root, f), src).replace(os.sep, "/"), args.ignore))
        if skipped:
            print(f"  （--ignore 剔除 {skipped} 个）")
    print(f"[DONE] {out}（{n} 个 .sfx，{total // 1024}KB"
          + (f"，{plain_n} 个明文豁免" if plain_n else "")
          + "）——目录结构保留、叶子哈希名")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="bundle.py", description="starfish 资源 bundle 打包器（规范锁死）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pack", help="目录 → 加密散文件 bundle")
    p.add_argument("--src", required=True, help="源资源目录")
    p.add_argument("--out", required=True, help="输出 bundle 目录（已存在则拒绝）")
    p.add_argument("--key", required=True, help="64 位 hex，或 @密钥文件路径")
    p.add_argument("--prefix", default="", help="逻辑路径前缀（如 assets——游戏加载路径相对游戏根时用）")
    p.add_argument("--magic", default="SFXE1", help="封装魔数（5 字符）")
    p.add_argument("--plain-ext", action="append", default=[],
                   help="明文豁免扩展（如 mp4——原路径原样拷贝零加密，大媒体直供原生解码器）")
    p.add_argument("--ignore", action="append", default=[],
                   help="剔除 glob（相对 src 的 POSIX 路径或文件名；可多次）")
    p.set_defaults(fn=cmd_pack)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
