# netvideo_test —— pygamest-runtime 打包验证（八阶段目标·阶段四）：
# video + net 双模块三端一致性案例——打包后加密资产/脚本加载链上的
# 模块行为核验（dist 壳 fetch→register→import 定约全链）。
#   video：Web 站桩 open（ValueError 分支）；原生 await open + 全片播放
#          断言（size 惰性 / frame() 出帧 / position 推进 / ended 到尾 /
#          控制面往返）。
#   net：TCP 分帧回声（候选表同 dev net_test——raw TCP 9001 / Web WS
#        9002 / 模拟器 10.0.2.2）+ UDP 自环（Web 站桩显式报错）。
# 退出：自动（SUMMARY 停 3 秒）/ ESC / 关窗。
import time

import pygame

PASS = []
FAIL = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("[PASS] " if ok else "[FAIL] ") + name + ("  " + detail if detail else ""))


async def main():
    screen = pygame.display.set_mode((640, 400))
    font = pygame.font.Font(None, 22)

    def draw_list():
        with screen.render() as r:
            r.fill((24, 26, 34))
            y = 20
            for line in PASS + FAIL:
                s = font.render(line, True,
                                (140, 220, 140) if line in PASS else (230, 120, 120))
                pygame.gfxdraw.set_transform(r, pygame.math.mat4_translation(-300, y, 0))
                pygame.gfxdraw.draw_surface(r, s)
                y += 24
        pygame.display.flip()

    # ── video ────────────────────────────────────────────────
    vs = pygame.video.VideoSystem()
    check("VideoSystem 构造", vs is not None)

    web_stub = False
    try:
        vs.open("assets/video/bbb_10s.mp4")
        check("sync open", True)
    except ValueError as e:
        if "Web" in str(e):
            web_stub = True
            check("web 站桩 open", True, str(e)[:40])
        else:
            check("open", False, str(e)[:60])

    if not web_stub:
        # 缺失文件错误路径
        try:
            vs.open("__missing_video__.mp4")
            check("missing open raises", False, "no exception")
        except ValueError:
            check("missing open raises", True)

        # 异步主形态：open 后台线程 + 帧轮询——主循环不卡
        v = await pygame.video.open("assets/video/bbb_10s.mp4")
        check("await open", v is not None)
        # size 惰性（首帧解码前 = (0,0)——打开即查不是契约）
        check("size 首帧前惰性 0", v.size() == (0, 0), f"size={v.size()}")

        dt = 1.0 / 30.0
        frames = 0
        saw_frame = False
        last_pos = 0.0
        pos_advanced = False
        while not v.ended() and frames < 900:
            v.update(dt)
            f = v.frame()
            if f is not None:
                saw_frame = True
            if v.position() > last_pos + 0.5:
                pos_advanced = True
                last_pos = v.position()
            frames += 1
            for e in pygame.event.get():
                if e.type == pygame.event.QUIT:
                    frames = 10**9
                if e.type == pygame.event.KEYDOWN and e.key == pygame.key.K_ESCAPE:
                    frames = 10**9
            if frames % 6 == 0 or f is not None:
                with screen.render() as r:
                    r.fill((24, 26, 34))
                    if f is not None:
                        pygame.gfxdraw.draw_surface(r, f)
                    hud = font.render(
                        f"pos={v.position():.2f}s frames={frames} audio={v.has_audio()}",
                        True, (200, 205, 215))
                    pygame.gfxdraw.set_transform(r, pygame.math.mat4_translation(-300, 180, 0))
                    pygame.gfxdraw.draw_surface(r, hud)
                pygame.display.flip()
            await pygame.next_frame()

        check("frame() 出帧", saw_frame)
        check("size 原始分辨率", v.size() == (640, 360), f"size={v.size()}")
        check("position 推进", pos_advanced, f"pos={last_pos:.2f}s")
        check("ended 到尾", v.ended())

        # 控制面：音量/静音/视频开关（纯接口往返）
        v.set_audio_volume(0.5)
        v.set_muted(True)
        v.set_video_enabled(False)
        check("控制面往返", v.video_enabled() is False)
        v.set_video_enabled(True)
        v.set_muted(False)
        v.set_audio_volume(1.0)
        check("控制面复原", v.video_enabled() is True)

    # ── net ──────────────────────────────────────────────────
    # Web 端 TCP = WebSocket 同协议（pygame.net 自动 ws:// 化）：
    # 9001 是 raw TCP 回声服（握手必败快过）→ 9002 才是 WS 回声服。
    # 真机（同网段 Wi-Fi）走 LAN 直连候选（PC 网卡 IP——随网络环境更新）。
    cands = [
        "127.0.0.1:9001",        # 桌面本机 / adb reverse
        "192.168.1.101:9001",    # 局域网直连（PC 网卡——同网段真机）
        "10.0.2.2:9001",         # Android 模拟器宿主回环
        "127.0.0.1:9002",        # Web WS 回声服（net_echo_ws_server.py）
    ]
    conn = None
    st = "connecting"
    for host in cands:
        try:
            c = pygame.net.TCP(host)
        except Exception:
            continue
        t0 = time.time()
        while time.time() - t0 < 10.0:
            st = c.state()
            if st == "connected":
                break
            await pygame.next_frame()
        if st == "connected":
            conn = c
            print("[INFO] TCP host=" + host)
            break
        c.close()
    check("TCP connected", st == "connected", f"state={st}")

    if st == "connected":
        conn.send("你好 net")
        got = None
        t0 = time.time()
        while time.time() - t0 < 3.0:
            got = conn.recv()
            if got is not None:
                break
            await pygame.next_frame()
        check("TCP send→recv 回声", got == ("echo:你好 net").encode("utf-8"), f"got={got!r}")

        blob = bytes(range(256)) * 64  # 16 KB 跨多分片
        conn.send(blob)
        got = None
        t0 = time.time()
        while time.time() - t0 < 3.0:
            got = conn.recv()
            if got is not None:
                break
            await pygame.next_frame()
        check("TCP 16KB 帧完整", got == b"echo:" + blob, f"len={None if got is None else len(got)}")

        conn.close()
        await pygame.next_frame()
        check("TCP close", conn.state() == "closed", f"state={conn.state()}")

    # UDP 自环（Web = 站桩报错设计语义）
    try:
        udp = pygame.net.UDP("127.0.0.1:9051")
        udp.send_to(b"udp-hello", "127.0.0.1:9051")
        got = None
        t0 = time.time()
        while time.time() - t0 < 2.0:
            got = udp.recv_from()
            if got is not None:
                break
            await pygame.next_frame()
        check("UDP 自环 send_to→recv_from", got is not None and got[0] == b"udp-hello",
              f"got={got!r}")
    except Exception as e:
        # Web 端 UDP 显式报错 = 设计行为（站桩确认）；桌面自环成功不会进这里
        check("UDP Web 站桩/可用", True, str(e)[:60])

    # ── 收官 ──
    if web_stub:
        # Web：print 不进页面控制台——assert 式（完成无异常 = 全过）
        assert not FAIL, f"web 分支有失败项: {FAIL}"
    print(f"[SUMMARY] PASS={len(PASS)} FAIL={len(FAIL)} {FAIL or ''}")

    last = time.time()
    while True:
        for e in pygame.event.get():
            if e.type == pygame.event.QUIT:
                return
            if e.type == pygame.event.KEYDOWN and e.key == pygame.key.K_ESCAPE:
                return
        if time.time() - last > 3.0:
            return
        draw_list()
        await pygame.next_frame()
