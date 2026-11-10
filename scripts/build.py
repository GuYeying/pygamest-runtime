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
    # 多平台扩展位（阶段六预留——适配层就绪即补 builder，见
    # pygamest reference/多平台扩展性架构分析与整改（阶段六）.md）：
    #   macos = .app bundle（starfish-we AppKit 后端 + video VideoToolbox
    #           后端已实装；打包脚本待建——codesign/Info.plist）
    #   ios   = .ipa（UIKit 后端 + Xcode 工程模板待建）
    #   ohos  = .hap（XComponent 适配层 + wgpu GL/EGL + OHAudio/AVPlayer
    #           待建——全部引擎侧扩展位已留，见报告 §Gap 表）
    reserved = {"macos", "ios", "ohos"}
    for t in targets:
        if t in reserved:
            print(f"[预留] {t} 打包适配层待建（引擎侧平台后端已就位——"
                  f"补 build_{t}.py 后在本表登记即可，架构零阻碍）")
            continue
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
