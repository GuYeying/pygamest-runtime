#!/usr/bin/env bash
# build_linux.sh —— pygamest-runtime Linux 打包（在 **Linux 机上**运行；
# Windows 交叉编译 Linux 需 sysroot，得不偿失——同 dev/build_linux.sh 铁律）。
#
# 用法（Ubuntu 20.04+ / Debian 系）：
#   chmod +x scripts/build_linux.sh
#   ./scripts/build_linux.sh
#
# 流程：系统依赖（winit=Wayland/X11、cpal=ALSA、gilrs=udev）→ cargo
# build runtime（Linux 壳）→ 打包管线（build_windows.py 已 OS 感知——
# 同一脚本在 Linux 上产出 dist/<游戏>/<游戏>（无 .exe 后缀）+ 资源
# bundle 散文件，密钥/剔除逻辑全同）。
set -euo pipefail
cd "$(dirname "$0")/.."

# ── 1/3 系统依赖（缺一样链接期报错）──────────────────────────────
if command -v apt-get >/dev/null 2>&1; then
    echo "=== 1/3 apt 依赖（sudo 需要时输密码）==="
    sudo apt-get update -qq
    sudo apt-get install -y -qq \
        build-essential pkg-config python3 \
        libxkbcommon-dev libwayland-dev libxkbcommon-x11-dev \
        libx11-dev libxcb1-dev \
        libasound2-dev libudev-dev
else
    echo "=== 1/3 非 apt 系统：请自备 C 工具链 + pkg-config +"
    echo "    wayland/xkbcommon/alsa/udev 开发库（跳过安装）"
fi

# ── 2/3 Rust 工具链（已有则跳过）─────────────────────────────────
if ! command -v cargo >/dev/null 2>&1; then
    echo "=== 2/3 未检测到 cargo——安装 rustup（默认 stable）==="
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
else
    echo "=== 2/3 cargo 已就绪：$(cargo --version)"
fi

# ── 3/3 打包（release 铁律同 Android；RP debug genesis 必败）────
echo "=== 3/3 打包管线（cargo build + 加密 + bundle）==="
python3 scripts/build_windows.py

BIN=dist/hello_word/hello_word
if [ -f "$BIN" ]; then
    echo
    echo "[OK] $BIN（$(du -h "$BIN" | cut -f1)）"
    echo "    试跑：./$BIN"
fi
