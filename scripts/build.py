#!/usr/bin/env python3
"""build.py——总控打包（读 pack.toml → 按 --target 分派 build_xxx）"""
import sys, os, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    targets = []
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pack.toml")
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--target":
            targets.append(sys.argv[i + 1]); i += 2
        elif sys.argv[i] == "--config":
            config_path = sys.argv[i + 1]; i += 2
        else:
            i += 1
    if not targets:
        targets = ["windows"]

    script_dir = os.path.dirname(os.path.abspath(__file__))
    crate_root = os.path.dirname(script_dir)
    # 各平台 builder：argv 形态不一（build_windows 吃 --config/--target，
    # android/wasm 是子命令/单发形态），逐条组装
    builders = {
        "windows": [sys.executable, os.path.join(script_dir, "build_windows.py"),
                    "--config", config_path, "--target", "windows"],
        "linux": ["bash", os.path.join(script_dir, "build_linux.sh")],
        "wasm": [sys.executable, os.path.join(script_dir, "build_wasm.py")],
        "android": [sys.executable, os.path.join(crate_root, "android", "build.py"), "demo"],
    }
    for t in targets:
        builder = builders.get(t)
        if not builder or not os.path.isfile(builder[1]) or (
                t == "linux" and not os.path.isfile(builder[2])):
            print(f"[FAIL] 未知平台或缺 builder: {t}")
            continue
        print(f"\n{'=' * 50}\n=== 构建 [{t}] ===\n{'=' * 50}")
        ret = subprocess.run(builder).returncode
        if ret != 0:
            print(f"[FAIL] {t} 构建失败（退出码 {ret}）")
            sys.exit(ret)
    print(f"\n=== 全部平台构建完成 ===")

if __name__ == "__main__":
    main()
