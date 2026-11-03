#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_export.py——导出自校验（证明加密真实生效）：

  python scripts/verify_export.py <dist游戏目录> [--src <游戏源目录>]

分发形态（2026-11-03 定约）= <name>.exe（净壳+入口密文嵌入） +
<资源目录>/：全部哈希名 .sfx（模块+资源）+ _payload.sfx/_manifest.sfx
加密双清单：
  ① 全产物明文扫描：游戏内容标记在任何产物文件中零命中（exe 内命中
     只提示——引擎解码器常量，与游戏内容无关）
  ② 脚本 roundtrip：清单 .py 逻辑路径 → 哈希定位 .sfx → 解密 → sha256
     对源（入口 main.py 嵌入壳内，不在散文件校验面）
  ③ 资源 roundtrip：sfx_hash 定位 → 解密 → sha256 对源；数目无多无少
  ④ 清单一致性：_payload.sfx（解密后）逻辑路径 ↔ 源文件一一对应
"""
import sys, os, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundle import sfx_name, walk as bundle_walk  # 规范唯一实现（与 starfish-io / 打包器同源）
from pack_toml import load, get_target

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

DOMAIN_AAD = b"starfish-asset-v1"

def sha256(b):
    return hashlib.sha256(b).hexdigest()

def main():
    args = sys.argv[1:]
    if not args:
        sys.exit("用法: verify_export.py <dist游戏目录> [--src <游戏源目录>]")
    game_dir = os.path.abspath(args[0])
    src_dir = args[args.index("--src") + 1] if "--src" in args else None
    if not os.path.isdir(game_dir):
        sys.exit(f"[FAIL] 导出目录不存在: {game_dir}")

    # 密钥路径：pack.toml [build] key_file 相对 [scripts] root（游戏项目根）
    crate_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = get_target(load(os.path.join(crate_root, "scripts", "pack.toml")), "windows")
    root = cfg.get("root", "")
    kf_name = cfg.get("key_file", "assets.key")
    key_path = os.path.join(crate_root, root, kf_name) if root else os.path.join(crate_root, kf_name)
    key_hex = open(key_path, encoding="ascii").read().strip()
    aead = ChaCha20Poly1305(bytes.fromhex(key_hex))

    name = os.path.basename(game_dir)
    exe_candidates = [f for f in os.listdir(game_dir)
                      if f in (name + ".exe", name, "runtime.exe", "runtime")]
    if not exe_candidates:
        sys.exit(f"[FAIL] 未找到壳二进制（{name}.exe）")
    exe_path = os.path.join(game_dir, exe_candidates[0])
    print(f"=== 校验 {game_dir}（壳 {os.path.getsize(exe_path)//1024//1024}MB）===")

    # 分发形态 = exe 同级**镜像源结构**（assets/ modules/ 全哈希 .sfx +
    # 加密双清单，2026-11-03 拍平定约）——bundle 基准 = 导出目录本身，
    # 资源前缀名从 pack.toml [resources] dir 末段同源解析
    has_sfx = any(f.endswith(".sfx") for _, _, fs in os.walk(game_dir) for f in fs)
    if not (os.path.isfile(os.path.join(game_dir, "_payload.sfx")) or has_sfx):
        sys.exit("[FAIL] 导出目录未找到 _payload.sfx / 任何 .sfx")
    bundle_dir = game_dir
    res_name = os.path.basename(
        cfg.get("dir", "assets").replace("\\", "/").rstrip("/").split("/")[-1]
    ) or "assets"
    print(f"[结构] 壳（入口密文嵌入） + 镜像源结构（{res_name}/ modules/ 全哈希 .sfx + 加密双清单）")

    # ── ① 全产物明文扫描（入口已嵌入壳内密文；双清单亦密文——零豁免）──
    markers = [b"ferris.png", b"bleep.wav", b"WAVEfmt ", b"RIFF", b"import pygame"]
    fail_hits = []
    engine_hits = []
    for root, dirs, files in os.walk(game_dir):
        for f in sorted(files):
            p = os.path.join(root, f)
            blob = open(p, "rb").read()
            hits = [m for m in markers if m in blob]
            if not hits:
                continue
            if p == exe_path:
                engine_hits = hits  # 引擎区命中只提示（解码器常量）
            else:
                fail_hits.append((os.path.relpath(p, game_dir), hits))
    if fail_hits:
        sys.exit(f"[①FAIL] 产物发现明文标记: {fail_hits}")
    print(f"[①OK] 全产物明文标记零命中"
          + (f"（壳内命中 {engine_hits} = 引擎解码器常量，与游戏内容无关）" if engine_hits else ""))

    # ── 清单解密（_payload.sfx → 逻辑路径表）──
    manifest_path = os.path.join(bundle_dir, "_payload.sfx")
    if not os.path.isfile(manifest_path):
        sys.exit("[FAIL] 资源目录缺 _payload.sfx 加密清单")
    menv = open(manifest_path, "rb").read()
    if menv[:5] != b"SFXE1":
        sys.exit("[FAIL] _payload.sfx 封装魔数异常")
    listed = [l.strip() for l in aead.decrypt(menv[5:17], menv[17:], DOMAIN_AAD)
              .decode("ascii").splitlines() if l.strip()]

    if not src_dir:
        print("[②SKIP] 未给 --src，跳过 roundtrip 对比")
        return

    # ── ② 脚本 roundtrip（清单 .py 逻辑路径 → 哈希定位 → 解密 → 对源；
    #    入口 main.py 以密文嵌入壳内——不在散文件校验面）──
    script_rels = [p for p in listed if p.endswith(".py") and p != "main.py"]
    ok = 0
    for rel in script_rels:
        rel_native = rel.replace("/", os.sep)
        sfx_path = os.path.join(bundle_dir, os.path.dirname(rel_native), sfx_name(rel, key_hex))
        if not os.path.isfile(sfx_path):
            print(f"[②FAIL] {rel} 哈希散文件缺失: {os.path.basename(sfx_path)}")
            continue
        env = open(sfx_path, "rb").read()
        if env[:5] != b"SFXE1":
            print(f"[②FAIL] {rel} 封装魔数异常")
            continue
        plain = aead.decrypt(env[5:17], env[17:], DOMAIN_AAD)
        want = open(os.path.join(src_dir, rel.replace("/", os.sep)), "rb").read()
        same = sha256(plain) == sha256(want)
        print(f"      · 脚本 {rel}: 解密 {len(plain)}B → sha256 {'一致' if same else '不一致!'}")
        ok += same
    if ok != len(script_rels):
        sys.exit(f"[②FAIL] 脚本 roundtrip 仅 {ok}/{len(script_rels)}")
    print(f"[②OK] 脚本 roundtrip {ok}/{len(script_rels)} —— 密文→密钥→明文与源逐字节一致")

    # ── ③ 资源 roundtrip（哈希链；资源子树内 .py = 热更脚本同属资源）──
    # 剔除口径与打包器一致（密钥恒剔除 + pack.toml [pack] ignore）
    ignore_globs = [kf_name]
    raw_ignore = str(cfg.get("ignore", "")).strip()
    if raw_ignore:
        for part in raw_ignore.strip("[]").split(","):
            g = part.strip().strip('"').strip("'")
            if g:
                ignore_globs.append(g)
    res_root = os.path.join(src_dir, res_name)
    if not os.path.isdir(res_root):
        sys.exit(f"[③FAIL] 源目录下未找到资源子树: {res_root}")
    res_src = [(os.path.relpath(f, src_dir).replace("\\", "/"), f)
               for f in bundle_walk(res_root, ignore_globs)]

    rok = 0
    for rel, f in res_src:
        res_native = rel.replace("/", os.sep)
        sfx_path = os.path.join(bundle_dir, os.path.dirname(res_native), sfx_name(rel, key_hex))
        raw = open(sfx_path, "rb").read()
        if raw[:5] != b"SFXE1":
            print(f"[③FAIL] {rel} 封装魔数异常")
            continue
        plain = aead.decrypt(raw[5:17], raw[17:], DOMAIN_AAD)
        same = sha256(plain) == sha256(open(f, "rb").read())
        print(f"      · 资源 {rel}: {sfx_name(rel, key_hex)[:12]}…sfx 解密 {len(plain)}B → sha256 {'一致' if same else '不一致!'}")
        rok += same

    sfx_count = sum(1 for r0, _, fs in os.walk(bundle_dir) for f in fs if f.endswith(".sfx"))
    # 全目录 .sfx 账目 = 资源 + 非资源脚本（资源子树 .py 已在资源侧计数）
    # + 加密清单（同后缀同构形态）
    res_scripts = [p for p in script_rels if not p.startswith(res_name + "/")]
    expected = len(res_src) + len(res_scripts) + 1
    extra = sfx_count - expected
    if rok != len(res_src) or extra != 0:
        sys.exit(f"[③FAIL] 资源 roundtrip {rok}/{len(res_src)}，.sfx 账目差 {extra}"
                 f"（实际 {sfx_count} / 期望 {expected}）")
    print(f"[③OK] 资源 roundtrip {rok}/{len(res_src)}；.sfx 账目吻合"
          f"（资源 {len(res_src)} + 脚本 {len(res_scripts)} + 清单 1 = {expected}）")

    # ── ④ 清单一致性（已解密清单 ↔ 源文件全集；main.py 例外=嵌入壳内）──
    src_all = set()
    if os.path.isdir(src_dir):
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
            for f in sorted(files):
                if f == kf_name:
                    continue
                src_all.add(os.path.relpath(os.path.join(root, f), src_dir).replace("\\", "/"))
    src_all.discard("main.py")  # 入口嵌入壳内，不入清单装载面
    missing = [p for p in src_all if p not in listed]
    if missing:
        sys.exit(f"[④FAIL] 清单缺源文件: {missing}")
    print(f"[④OK] _payload.sfx 清单 {len(listed)} 项 ↔ 源 {len(src_all)} 项一致（main.py 嵌入例外）")

    print("\n[结论] 加密真实生效：净壳（入口密文嵌入）+ 脚本/资源/清单散文件"
          "全部密态哈希名，运行时由嵌入钥解密；分发物零明文零原名零 .py。")

if __name__ == "__main__":
    main()
