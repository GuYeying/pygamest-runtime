#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_wasm.py——pygamest-runtime Web 构建（多文件明文形态，v1 定约）。

用法：
  python scripts/build_wasm.py [--game hello_word] [--features 轴列表] [--no-default-features]

流程：
  1. wasm-bindgen-cli 版本自检（与 Cargo.lock 严格一致）
  2. cargo build --release --target wasm32-unknown-unknown --bin runtime
  3. wasm-bindgen → dist/<game>-web/（runtime.js + runtime_bg.wasm）
  4. 写宿主页 index.html（**自动点火**——壳 wasm start 即 fetch main.py
     运行，页面零交互）
  5. 部署游戏 payload：main.py + modules/ + assets/ **原地加密**（SFXE1
     封装、文件名保留）+ _payload.txt 清单——壳启动期 fetch 全部预载进
     io 内存表（读取时按嵌入钥解密；sync API 的字节来源）

测试：<out> 起静态服务（file:// 受 CORS 限制），浏览器打开 index.html。
"""

import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

DOMAIN_AAD = b"starfish-asset-v1"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CRATE = Path(__file__).resolve().parent.parent
TARGET_DIR = CRATE / "target" / "wasm32-unknown-unknown" / "release"
LOCK = CRATE / "Cargo.lock"

# 自动点火宿主页：canvas id = starfish-we（引擎表面挂载锚点）；壳的
# wasm start（app_entry! → __starfish_app_entry）在 init() 后自动
# fetch main.py 运行——页面零交互，无任何脚本参数面（锁定语义）。
INDEX_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<!-- viewport（2026-11-14 手机实测定案）：无此 meta 手机浏览器按 980px
     布局视口渲染再缩放——canvas css 尺寸异常 = egui UI 比例异常 +
     input 聚焦缩放的总根源。user-scalable=no 同封聚焦缩放/双击缩放 -->
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>pygamest-runtime</title>
<style>
  html, body { margin: 0; height: 100%; background: #000; color: #ccc;
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; }
  canvas { outline: none; max-width: 96vw; max-height: 82vh; }
  #wlog { width: calc(100% - 24px); box-sizing: border-box; height: 120px;
    overflow-y: auto; padding: 4px 8px; white-space: pre-wrap;
    color: #9c9; background: #111; border: 1px solid #222; border-radius: 4px;
    font: 11px/1.5 Consolas, monospace; text-align: left; }
</style>
</head>
<body>
<canvas id="starfish-we"></canvas>
<pre id="wlog"></pre>
<script>
const _wl = document.getElementById('wlog');
_wl.textContent += '[build] ' + '__BUILD_TS__' + '\n';
const _fmt = a => a.map(x => { try {
  return (x && x.message !== undefined) ? x.message : String(x);
} catch (e) { return '<unprintable>'; } }).join(' ');
for (const m of ['log', 'info', 'warn', 'error']) {
  const orig = console[m].bind(console);
  console[m] = (...a) => {
    _wl.textContent += '[' + m + '] ' + _fmt(a) + '\n';
    const lines = _wl.textContent.split('\n');
    if (lines.length > 200) _wl.textContent = lines.slice(-200).join('\n');
    _wl.scrollTop = _wl.scrollHeight;
    orig(...a);
  };
}
window.addEventListener('error', e => {
  _wl.textContent += '[onerror] ' + (e.message || e.error) + '\n';
});
window.addEventListener('unhandledrejection', e => {
  _wl.textContent += '[rejection] ' + e.reason + '\n';
});
</script>
<script type="module">
import init from './runtime.js?v=__BUILD_TS__';
init({ module_or_path: './runtime_bg.wasm?v=__BUILD_TS__' });
</script>
</body>
</html>
"""


def sh(cmd, tail=0):
    print("+", " ".join(str(c) for c in cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
        sys.exit(f"[FAIL] 命令失败: {cmd[0]} …")
    if tail:
        print("\n".join(r.stdout.splitlines()[-tail:]))
    return r.stdout


def check_bindgen_version():
    """wasm-bindgen-cli 必须与 Cargo.lock 的 wasm-bindgen 严格一致。"""
    r = subprocess.run(["wasm-bindgen", "--version"], capture_output=True, text=True)
    m_cli = re.search(r"(\d+\.\d+\.\d+)", r.stdout)
    cli = m_cli.group(1) if m_cli else None
    lock_ver = None
    if LOCK.is_file():
        m_lock = re.search(r'name = "wasm-bindgen"\nversion = "([^"]+)"',
                           LOCK.read_text(encoding="utf-8"))
        lock_ver = m_lock.group(1) if m_lock else None
    print(f"[版本] wasm-bindgen-cli = {cli} / Cargo.lock = {lock_ver}")
    if cli != lock_ver:
        sys.exit(f"[FAIL] 版本不一致（cli {cli} ≠ lock {lock_ver}）——重装："
                 f"cargo install wasm-bindgen-cli --version {lock_ver}")


def deploy_game(out: Path, game_dir: Path, kf: Path, magic: bytes):
    """游戏 payload **原地加密**部署（文件名保留、内容 SFXE1 封装）+
    _payload.sfx 加密清单——模块/资源 fetch 预载（读取时解密）。
    入口 main.py **不入部署**（build.rs 编译期加密嵌入 wasm 二进制，
    2026-11-03 用户定约——磁盘零 main 文件）。

    陈旧 payload 清理（2026-11-03 实测泄漏）：out 目录混载 host 产物
    （index.html/runtime.js/wasm——bindgen 重复生成）与 payload，不清
    会残留旧部署文件（实测 main.py.bak **明文源码**漏在分发物里）——
    部署前先删 payload 根（main.py* / modules/ / assets/ / _payload.*），
    host 产物不动。"""
    if not (game_dir / "main.py").is_file():
        sys.exit(f"[FAIL] 游戏入口缺失: {game_dir / 'main.py'}")
    # ── 陈旧 payload 清理（含历史遗留变体：bak/旧清单名）──
    for stale in ["main.py", "main.py.bak", "_payload.txt", "_payload.sfx",
                  "modules", "assets"]:
        p = out / stale
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    key = bytes.fromhex(kf.read_text(encoding="ascii").strip())
    aead = ChaCha20Poly1305(key)

    def encrypt_write(src: Path, dst: Path):
        data = src.read_bytes()
        nonce = secrets.token_bytes(12)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(magic + nonce + aead.encrypt(nonce, data, DOMAIN_AAD))

    payload = []
    n_mod = 0
    mods = game_dir / "modules"
    if mods.is_dir():
        for py in mods.rglob("*.py"):
            if any(p.startswith((".", "__pycache__")) for p in py.relative_to(mods).parts):
                continue
            rel = (Path("modules") / py.relative_to(mods)).as_posix()
            encrypt_write(py, out / rel)
            payload.append(rel)
            n_mod += 1
    n_res = 0
    res = game_dir / "assets"
    if res.is_dir():
        for f in res.rglob("*"):
            if f.is_file() and not f.name.startswith(".") and f.suffix != ".log":
                rel = (Path("assets") / f.relative_to(res)).as_posix()
                encrypt_write(f, out / rel)
                payload.append(rel)
                n_res += 1
    manifest = ("\n".join(payload) + "\n").encode("ascii")
    nonce = secrets.token_bytes(12)
    (out / "_payload.sfx").write_bytes(magic + nonce + aead.encrypt(nonce, manifest, DOMAIN_AAD))
    print(f"[OK] payload 加密：模块 {n_mod} + 资源 {n_res} + 加密清单（入口已嵌入 wasm）")


def _argv_value(flag: str, default: str = "") -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    game = _argv_value("--game", "hello_word")
    features = _argv_value("--features")
    no_default = "--no-default-features" in sys.argv
    game_dir = CRATE / "examples" / game
    out = CRATE / "dist" / f"{game}-web"

    check_bindgen_version()
    print("=== 构建 wasm runtime（bin runtime）===")
    cargo_cmd = ["cargo", "+nightly", "build", "--release", "--target",
                 "wasm32-unknown-unknown", "--bin", "runtime"]
    if no_default:
        cargo_cmd.append("--no-default-features")
    if features:
        cargo_cmd += ["--features", features]
    sh(cargo_cmd, tail=1)
    wasm = TARGET_DIR / "runtime.wasm"
    if not wasm.is_file():
        sys.exit(f"[FAIL] wasm 产物缺失: {wasm}")

    out.mkdir(parents=True, exist_ok=True)
    print("=== wasm-bindgen 后处理 ===")
    sh(["wasm-bindgen", "--out-dir", str(out), "--target", "web", str(wasm)])
    build_ts = datetime.now().strftime("%Y%m%d%H%M%S")
    (out / "index.html").write_text(
        INDEX_TEMPLATE.replace("__BUILD_TS__", build_ts), encoding="utf-8")

    print("=== 部署游戏 payload（加密 + 清单）===")
    kf = game_dir / "assets.key"
    if not kf.is_file():
        key_hex = secrets.token_bytes(32).hex()
        kf.write_text(key_hex, encoding="ascii")
        print(f"[KEY] 密钥缺失，已自动生成: {kf}")
    deploy_game(out, game_dir, kf, b"SFXE1")

    print(f"\n[DONE] {out}")
    print(f"  测试：cd {out} 后起静态服务（如 /d/miniconda3/python.exe -m http.server 8124），")
    print("  浏览器打开 index.html——壳自动 fetch 清单预载（解密）后运行，页面零交互。")


if __name__ == "__main__":
    main()
