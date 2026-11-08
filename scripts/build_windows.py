#!/usr/bin/env python3
"""build_windows.py——桌面导出（系统 CPython 上跑，零引擎依赖）：

  python scripts/build_windows.py [--config pack.toml] [--target linux]

分工（打包规范唯一实现 = bundle.py，本脚本只编排）：
  资源 → bundle.py → dist/<name>/<资源目录>/ 哈希名 .sfx 散文件
  脚本 → 游戏根下全量 .py 扫描（**剔除资源子树**）→ 加密 → **哈希名
         .sfx**（与资源同构——.py 后缀零出现，原名只在加密清单里；
         io 读链按逻辑路径哈希定位解密）
  入口 → build.rs 编译期加密嵌入 exe（磁盘零 main 文件）
  清单 → `<资源目录>/_payload.sfx`（逻辑路径表，密文；壳启动解密装表
         ——fetch→register→import 定约）
产物 = dist/<name>/ = <name>.exe（净壳+嵌入入口） + <资源目录>/（全
.sfx + 加密清单）——分发物零明文零原名零 .py。
资源目录名同源 pack.toml [resources] dir 末段——build.rs 解析同一份
编译进壳（RES_DIR_NAME），双端一致。
"""
import sys, os, subprocess, shutil, secrets, fnmatch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pack_toml import load, get_target
from bundle import sfx_name  # 规范唯一实现（哈希名与 io 读链同源）

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
AAD = b"starfish-asset-v1"

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    crate_root = os.path.dirname(script_dir)
    config_path = os.path.join(script_dir, "pack.toml")
    target = "windows"
    for i, a in enumerate(sys.argv):
        if a == "--config":
            config_path = sys.argv[i + 1]
        if a == "--target":
            target = sys.argv[i + 1]

    cfg = get_target(load(config_path), target)
    name = cfg.get("name", "game")
    entry = cfg.get("entry", "main")
    key_file = cfg.get("key_file", "assets.key")
    magic = cfg.get("magic", "SFXE1").encode()

    def abs_path(p, default):
        p = p or default
        return p if os.path.isabs(p) else os.path.join(crate_root, p)

    scripts_dir = abs_path(cfg.get("root"), os.path.join(crate_root, "examples", name))
    res_dir = abs_path(cfg.get("dir"), os.path.join(scripts_dir, "assets"))
    out_root = abs_path(cfg.get("out"), os.path.join(crate_root, "dist"))

    # 密钥：**游戏项目根**下（pack.toml [build] key_file 相对 [scripts] root）
    # ——每游戏一份；缺失 = 自动生成写入。旧逻辑为全零密钥静默兜底，
    # 弱密钥隐患，已废除。
    kf = os.path.join(scripts_dir, key_file)
    if not os.path.isfile(kf):
        key_hex_new = secrets.token_bytes(32).hex()
        open(kf, "w", encoding="ascii").write(key_hex_new)
        print(f"[KEY] 密钥缺失，已自动生成: {kf}（{key_hex_new[:16]}…）——勿入分发、建议 .gitignore")
    key_hex = open(kf, encoding="ascii").read().strip()
    key = bytes.fromhex(key_hex)
    aead = ChaCha20Poly1305(key)

    # 剔除 glob：密钥文件**恒剔除**（默认剔除项，无需配置）+ pack.toml
    # [pack] ignore 追加。对资源 bundle 生效。
    ignore_globs = [key_file]
    raw_ignore = str(cfg.get("ignore", "")).strip()
    if raw_ignore:
        for part in raw_ignore.strip("[]").split(","):
            g = part.strip().strip('"').strip("'")
            if g:
                ignore_globs.append(g)

    # 资源逻辑路径相对游戏根（scripts root）——bundle.py 用 --prefix 还原
    # （<资源目录>/ 前缀随逻辑路径进清单；build.rs 同源解析为 RES_DIR_NAME
    # = 壳侧模块注册的资源前缀判据）
    prefix = os.path.relpath(res_dir, scripts_dir).replace("\\", "/")
    prefix = "" if prefix == "." else prefix

    # OS 感知（Windows 上开发/打包；--target linux 或在 Linux 机上跑 =
    # Linux 形态——产物无 .exe 后缀，壳二进制名 runtime 同源）
    exe_suffix = ".exe" if os.name == "nt" and target != "linux" else ""
    plat_name = "Windows" if exe_suffix else "Linux"
    print(f"=== [{name}] {plat_name} 构建（散文件 + 清单形态） ===")
    print("[1/5] cargo build --bin runtime")
    subprocess.run(["cargo", "+nightly", "build", "--release", "--bin", "runtime"],
                   check=True, cwd=crate_root)
    runtime_exe = os.path.join(crate_root, "target", "release", "runtime" + exe_suffix)

    # ── 2) 资源 → bundle.py（规范唯一实现；bundle 自建 out 目录防覆盖。
    #    out = dist 根——逻辑路径自带 <资源目录>/ 前缀，产物镜像源结构：
    #    assets/ modules/ 与 exe 同级，2026-11-03 用户定约）──
    dist_game = os.path.join(out_root, name)
    if os.path.isdir(dist_game):
        shutil.rmtree(dist_game)
    print(f"[2/5] 资源 → bundle.py（dist/{name}/assets/… 镜像源结构）")
    bundle_cmd = [sys.executable, os.path.join(script_dir, "bundle.py"), "pack",
                  "--src", res_dir, "--out", dist_game,
                  "--key", "@" + kf, "--prefix", prefix,
                  "--magic", magic.decode()]
    for g in ignore_globs:
        bundle_cmd += ["--ignore", g]
    subprocess.run(bundle_cmd, check=True)

    # ── 3) 脚本收集 → 加密 → **哈希名 .sfx**（资源子树剔除——里面的 .py
    #    属资源/热更；.py 后缀从分发物消失，原名只在加密清单里）──
    print("[3/5] 脚本收集+加密（哈希名散文件）")
    payload = []      # 清单：逻辑路径（相对游戏根）
    for root, dirs, files in os.walk(scripts_dir):
        dirs[:] = [
            d for d in dirs
            if not d.startswith((".", "__pycache__"))
            and not (prefix and os.path.relpath(
                os.path.join(root, d), scripts_dir).replace("\\", "/") == prefix)
        ]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            src_path = os.path.join(root, f)
            rel = os.path.relpath(src_path, scripts_dir).replace("\\", "/")
            if rel == entry + ".py":
                continue  # 入口已由 build.rs 嵌入 exe——不入部署/清单
            data = open(src_path, "rb").read()
            nonce = os.urandom(12)
            env = magic + nonce + aead.encrypt(nonce, data, AAD)
            rel_native = rel.replace("/", os.sep)
            dst = os.path.join(dist_game, os.path.dirname(rel_native), sfx_name(rel, key_hex))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(env)
            payload.append(rel)
    print(f"  脚本 {len(payload)} 个")
    script_count = len(payload)

    # ── 4) 资源逻辑路径并入清单（相对游戏根 = <资源目录>/…；bundle 的
    #    哈希链按逻辑路径解析——壳侧 io 读链同构）──
    for root, dirs, files in os.walk(res_dir):
        dirs[:] = [d for d in dirs if not d.startswith((".", "__pycache__"))]
        for f in sorted(files):
            rel = os.path.relpath(os.path.join(root, f), scripts_dir).replace("\\", "/")
            parts = rel.split("/")
            if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(parts[-1], g)
                   for g in ignore_globs):
                continue
            payload.append(rel)

    # ── 5) 清单落盘（`_payload.sfx`——逻辑路径表也密态）+ 净壳拷贝 ──
    manifest_data = ("\n".join(payload) + "\n").encode("ascii")
    nonce = os.urandom(12)
    env = magic + nonce + aead.encrypt(nonce, manifest_data, AAD)
    with open(os.path.join(dist_game, "_payload.sfx"), "wb") as fh:
        fh.write(env)
    out_exe = os.path.join(dist_game, name + exe_suffix)
    shutil.copy2(runtime_exe, out_exe)
    size = os.path.getsize(out_exe)
    print(f"[DONE] dist/{name}/ = {name}{exe_suffix}（{size // 1024 // 1024}MB 净壳+嵌入入口）"
          f" + assets/ modules/ 同级（镜像源结构，全 .sfx + 加密清单 {len(payload)} 项）")

if __name__ == "__main__":
    main()
