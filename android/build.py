#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pygamest-runtime Android 打包（**NativeActivity 自管理形态**）。

与 dev 的 Java UI 注入形态的根本差异：
  - 清单 = android.app.NativeActivity（hasCode=false，无 dex）——dlopen
    libruntime_android.so 调 android_main，窗口/事件由 starfish-we 经
    android_native_app_glue **自管**（无代码注入/无 surface 注入/无事件注入）
  - **脚本 + 资源** = 全部打进 APK assets/<res>/（SFIX1 .so trailer 退役
    2026-11-03，与桌面散文件+清单形态同构）：资源 = bundle.py 哈希名
    .sfx；脚本 = 保原名加密 .py；`_payload.txt` = 逻辑路径清单（壳启动
    装表，fetch→register→import 定约）；`_manifest.txt` = 物理文件名
    清单（启动经 AssetManager 展开到内部存储，增量）——base_dir 指向
    解压处，io 读链在 native 完全复用
  - 横竖屏：pack.toml [android] orientation（Android 原生取值，
    landscape / portrait / sensorLandscape / sensorPortrait…）
  - 全屏尺寸等参数：驱动 Android 分支自动取 external_size 透传 sys.argv

用法：
  python android/build.py [--skip-build] [--install] [--game hello_word]
产物：target/apk/<game>.apk
前置：D:/SDK/Android、~/.android/debug.keystore、cargo-ndk、JDK
"""

import argparse
import secrets
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from bundle import sfx_name  # 规范唯一实现（资源散文件命名与桌面同源）
from pack_toml import load

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

DOMAIN_AAD = b"starfish-asset-v1"
CRATE = Path(__file__).resolve().parent.parent
ANDROID = CRATE / "android"
JNI_LIBS = ANDROID / "jniLibs"
ABI = "arm64-v8a"
LIB_NAME = "runtime_android"          # 清单 lib_name（dlopen 锚点）
SO_NAME = f"lib{LIB_NAME}.so"
OUT_DIR = CRATE / "target" / "apk"
WORK = CRATE / "target" / "apk_build"


def sh(cmd, cwd=None, tail=0):
    print("+", " ".join(str(c) for c in cmd))
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
        sys.exit(f"[FAIL] 命令失败: {cmd[0]} …")
    out = (r.stdout + r.stderr).strip()
    if tail:
        print("\n".join(out.splitlines()[-tail:]))
    return out


def best_subdir(base: Path, prefix: str) -> Path:
    cands = [p for p in base.glob(f"{prefix}*") if p.is_dir()] if base.is_dir() else []
    if not cands:
        sys.exit(f"[FAIL] 未找到 {base}/{prefix}*（检查 SDK 安装）")
    return max(cands, key=lambda p: [int(x) if x.isdigit() else 0 for x in p.name.split(".")])


def main():
    ap = argparse.ArgumentParser(description="pygamest-runtime Android 打包（NativeActivity 自管理）")
    ap.add_argument("--skip-build", action="store_true", help="复用现有 .so（调试迭代）")
    ap.add_argument("--install", action="store_true", help="构建后 adb install -r 并启动")
    ap.add_argument("--game", default="hello_word", help="游戏目录名（examples/<game>）")
    args = ap.parse_args()
    game_dir = CRATE / "examples" / args.game
    if not game_dir.is_dir():
        sys.exit(f"[FAIL] 游戏目录不存在: {game_dir}")

    # 配置（pack.toml 单一配置源）
    cfg = load(CRATE / "scripts" / "pack.toml").get("android", {})
    orientation = cfg.get("orientation", "landscape")

    sdk = Path("D:/SDK/Android")
    bt = best_subdir(sdk / "build-tools", "")
    jar = best_subdir(sdk / "platforms", "android-") / "android.jar"
    ndk = best_subdir(sdk / "ndk", "")
    ndk_bin = ndk / "toolchains" / "llvm" / "prebuilt" / "windows-x86_64" / "bin"

    # 密钥：游戏项目根（与桌面同源——缺失自动生成）
    kf = game_dir / "assets.key"
    if not kf.is_file():
        key_hex = secrets.token_bytes(32).hex()
        kf.write_text(key_hex, encoding="ascii")
        print(f"[KEY] 密钥缺失，已自动生成: {kf}")
    key = bytes.fromhex(kf.read_text(encoding="ascii").strip())
    magic = b"SFXE1"

    # 剔除 glob：密钥恒剔除 + pack.toml [pack] ignore（与桌面同源）
    import fnmatch
    ignore_globs = [kf.name]
    raw_ignore = str(load(CRATE / "scripts" / "pack.toml").get("pack", {}).get("ignore", "")).strip()
    if raw_ignore:
        for part in raw_ignore.strip("[]").split(","):
            g = part.strip().strip('"').strip("'")
            if g:
                ignore_globs.append(g)

    # 1) 交叉编译（release 铁律；example runtime_android = bin 同源 cdylib）
    so = JNI_LIBS / ABI / SO_NAME
    if not args.skip_build:
        print(f"=== 1/5 cargo ndk build ({ABI}，NativeActivity 自管理 cdylib) ===")
        sh(["cargo", "+nightly", "ndk", "-t", ABI, "-P", "26", "-o", str(JNI_LIBS),
            "--", "build", "--release", "--example", "runtime_android"], tail=1)
    if not so.is_file():
        sys.exit(f"[FAIL] .so 缺失: {so}")
    print("=== 2/5 llvm-strip + android_main 自检 ===")
    sh([str(ndk_bin / "llvm-strip"), str(so)])
    nm = sh([str(ndk_bin / "llvm-nm"), "-D", str(so)])
    if "T android_main" not in nm:
        sys.exit("[FAIL] android_main 未导出（NativeActivity 无法启动）——检查 app_entry! 接线")
    print("[nm] android_main 已导出 ✓")

    # 3) 脚本+资源 → APK assets/<res>/（散文件 + 清单——与桌面同构；
    #    .so 纯净无附加体，重复打包天然幂等）
    print("=== 3/5 脚本+资源 → APK assets（散文件+清单） ===")
    res_dir = game_dir / "assets"
    res_name = res_dir.name
    prefix = res_name  # 资源逻辑路径 = 游戏根视角的 assets/xxx
    aead = ChaCha20Poly1305(key)
    assets_root = WORK / "assets_root"
    if assets_root.is_dir():
        shutil.rmtree(assets_root)
    # **拍平镜像源结构**（2026-11-03 用户定约）：APK assets 根 = 游戏根
    # （modules/… assets/… 双清单都在根）——展开后 data_dir 镜像源布局，
    # 与桌面 exe 同级形态同构。bundle 自建 out 目录（防覆盖），脚本/
    # 清单在其后写入同一目录
    res_out = assets_root

    payload = []   # _payload.sfx：逻辑路径清单（壳装表）

    # 3a) 资源 → bundle.py 哈希名 .sfx（bundle 自建 out 目录防覆盖——
    #     脚本散文件在其后写入同一目录）
    bundle_cmd = [sys.executable, str(CRATE / "scripts" / "bundle.py"), "pack",
                  "--src", str(res_dir), "--out", str(res_out),
                  "--key", "@" + str(kf), "--prefix", prefix,
                  "--magic", magic.decode()]
    for g in ignore_globs:
        bundle_cmd += ["--ignore", g]
    subprocess.run(bundle_cmd, check=True, cwd=CRATE)

    # 3b) 脚本（游戏全量 .py，剔资源子树——资源子树内 .py 属热更走资源
    #     侧）→ 加密 → **哈希名 .sfx**（与资源同构：分发物零 .py 后缀、
    #     零原名；入口 main 已由 build.rs 嵌入 .so——不入清单装载链）
    for py in sorted(game_dir.rglob("*.py")):
        rel = py.relative_to(game_dir).as_posix()
        if any(p.startswith((".", "__pycache__")) for p in rel.split("/")):
            continue
        if rel.startswith(res_name + "/"):
            continue  # 资源子树内 .py = 热更脚本，属资源——脚本遍历剔除
        if rel == "main.py":
            continue  # 入口已由 build.rs 嵌入 .so——不入部署/清单
        nonce = secrets.token_bytes(12)
        env = magic + nonce + aead.encrypt(nonce, py.read_bytes(), DOMAIN_AAD)
        # 目录结构保留：哈希文件写原目录位（modules/<hash>.sfx）
        dst = res_out / Path(rel).parent / sfx_name(rel, key.hex())
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(env)
        payload.append(rel)
    print(f"[OK] 脚本 {len(payload)} 个（哈希名 .sfx；入口已嵌入 .so）")

    # 3c) 资源逻辑路径并入清单 + 双清单落盘（**均密文**）：
    #    _payload.sfx = 逻辑路径（壳装表）；_manifest.sfx = 物理文件名
    #    （启动经 AssetManager 解密展开表逐个复制）。资源清单条目与
    #    bundle 同滤（ignore 对齐桌面）。
    for f in sorted(res_dir.rglob("*")):
        if not f.is_file() or f.name.startswith((".", "__pycache__")):
            continue
        rel = f.relative_to(game_dir).as_posix()
        if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(f.name, g)
               for g in ignore_globs):
            continue
        payload.append(rel)

    def _write_sfx(dst: Path, data: bytes):
        nonce = secrets.token_bytes(12)
        dst.write_bytes(magic + nonce + aead.encrypt(nonce, data, DOMAIN_AAD))

    _write_sfx(res_out / "_payload.sfx", ("\n".join(sorted(payload)) + "\n").encode("ascii"))
    physical = sorted(p.relative_to(res_out).as_posix() for p in res_out.rglob("*") if p.is_file())
    _write_sfx(res_out / "_manifest.sfx", ("\n".join(physical) + "\n").encode("ascii"))
    print(f"[OK] 加密清单 {len(payload)} 项（payload）/ {len(physical)} 文件（manifest 展开表）")

    # 4) manifest 替换（lib_name 根治点 + orientation 配置）+ aapt2 link
    print("=== 4/5 aapt2 link（lib_name/orientation 对齐）===")
    WORK.mkdir(parents=True, exist_ok=True)
    ver_code = time.strftime("%m%d%H%M%S")
    build_id = "rt-" + time.strftime("%Y%m%d-%H%M%S")
    mtext = (ANDROID / "AndroidManifest.xml").read_text(encoding="utf-8")
    mtext = (mtext.replace("__LIB_NAME__", LIB_NAME)
                  .replace("__ORIENTATION__", orientation)
                  .replace("__GAME_NAME__", args.game)
                  .replace('android:versionCode="1"', f'android:versionCode="{ver_code}"')
                  .replace('android:versionName="0.1.0"', f'android:versionName="{build_id}"'))
    m = WORK / "AndroidManifest.xml"
    m.write_text(mtext, encoding="utf-8")
    base_apk = WORK / "base.apk"
    link_args = [str(bt / "aapt2.exe"), "link", "--manifest", str(m), "-I", str(jar),
                 "-A", str(assets_root), "-o", str(base_apk)]
    res_dir_t = ANDROID / "res"
    if res_dir_t.is_dir():
        res_zip = WORK / "res.zip"
        sh([str(bt / "aapt2.exe"), "compile", "--dir", str(res_dir_t), "-o", str(res_zip)])
        link_args.append(str(res_zip))
    sh(link_args)

    # 5) 组装（仅 .so——hasCode=false 无 dex）+ zipalign + 签名 + lib_name 自检
    print("=== 5/5 组装 + zipalign + apksigner ===")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    final = OUT_DIR / f"{args.game}.apk"
    tmp_full = WORK / "full.apk"
    with zipfile.ZipFile(base_apk) as zb, zipfile.ZipFile(tmp_full, "w") as zout:
        for item in zb.infolist():
            zout.writestr(item, zb.read(item.filename))
        zout.writestr(f"lib/{ABI}/{SO_NAME}", so.read_bytes(),
                      compress_type=zipfile.ZIP_DEFLATED)
    aligned = WORK / "aligned.apk"
    sh([str(bt / "zipalign.exe"), "-f", "4", str(tmp_full), str(aligned)])
    ks = Path.home() / ".android" / "debug.keystore"
    if not ks.is_file():
        sys.exit(f"[FAIL] 未找到签名 keystore: {ks}")
    sh([str(bt / "apksigner.bat"), "sign", "--ks", str(ks), "--ks-pass", "pass:android",
        "--out", str(final), str(aligned)])
    sh([str(bt / "apksigner.bat"), "verify", str(final)])
    badging = subprocess.run([str(bt / "aapt2.exe"), "dump", "xmltree", "--file",
                              "AndroidManifest.xml", str(final)],
                             capture_output=True, text=True, errors="replace")
    if f'"{LIB_NAME}"' not in badging.stdout:
        sys.exit("[FAIL] lib_name 自检失败——禁止分发")
    print(f"[自检] lib_name={LIB_NAME} ✓ orientation={orientation} ✓")
    tmp_full.unlink(missing_ok=True)
    aligned.unlink(missing_ok=True)
    print(f"[DONE] {final}（{final.stat().st_size // 1024 // 1024} MB；脚本+资源 assets 展开，NativeActivity 自管理）")

    if args.install:
        adb = "D:/android-tools/platform-tools/adb.exe"
        sh([adb, "install", "-r", str(final)], tail=1)
        sh([adb, "shell", "am", "start",
            "-n", f"com.starfish.runtime/android.app.NativeActivity"], tail=1)


if __name__ == "__main__":
    main()
