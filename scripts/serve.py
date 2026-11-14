#!/usr/bin/env python3
"""serve.py —— 局域网测试静态服务器（防缓存版）。

http.server 默认不发缓存头，手机浏览器对 index/wasm 会 heuristic 缓存——
wasm 更新后手机强刷仍可能命中旧版（2026-11-14 egui_app 实测）。本服务器
对所有响应加 no-store，测试页永远拿最新产物。

用法：
  python scripts/serve.py [目录] [端口]
  默认目录 = dist（runtime 产物根），默认端口 8124
"""
import functools
import http.server
import os
import sys
from pathlib import Path


class NoStoreHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def main():
    root = Path(__file__).resolve().parent.parent / "dist"
    port = 8124
    args = sys.argv[1:]
    if args:
        root = Path(args[0]).resolve()
    if len(args) > 1:
        port = int(args[1])
    handler = functools.partial(NoStoreHandler, directory=str(root))
    print(f"[serve] {root} @ 0.0.0.0:{port}（no-store）")
    http.server.test(HandlerClass=handler, port=port, bind="0.0.0.0")


if __name__ == "__main__":
    main()
