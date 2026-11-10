# video_test —— pygame.video 三端一致性案例：打开 BBB 10s 测试片
# （assets/video/bbb_10s.mp4，CC-BY test-videos.co.uk）→ 逐帧驱动 →
# frame() Surface 上屏 + 控制面断言（size/position/ended/audio 开关）。
# 退出：ESC / 关窗（播放完自动 SUMMARY + 停 2 秒）。
import time

import pygame

PASS = []
FAIL = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("[PASS] " if ok else "[FAIL] ") + name + ("  " + detail if detail else ""))


async def main():
    screen = pygame.display.set_mode((960, 540))
    font = pygame.font.Font(None, 24)

    vs = pygame.video.VideoSystem()
    check("VideoSystem 构造", vs is not None)

    # 端检测（异常驱动）：Web 站桩 open 一触即显式 ValueError
    v = None
    try:
        v = vs.open("assets/video/bbb_10s.mp4")
    except ValueError as e:
        if "Web" in str(e):
            check("web 站桩 open", True, str(e)[:40])
            assert not FAIL, f"web 分支有失败项: {FAIL}"
            print(f"[SUMMARY] PASS={len(PASS)} FAIL={len(FAIL)} {FAIL or ''}")
            last = time.time()
            while True:
                for e in pygame.event.get():
                    if e.type == pygame.event.QUIT or (
                        e.type == pygame.event.KEYDOWN and e.key == pygame.key.K_ESCAPE):
                        return
                if time.time() - last > 2.0:
                    return
                await pygame.next_frame()
        else:
            check("open", False, str(e)[:60])

    # 缺失文件错误路径
    try:
        vs.open("__missing_video__.mp4")
        check("missing open raises", False, "no exception")
    except ValueError:
        check("missing open raises", True)

    v = vs.open("assets/video/bbb_10s.mp4")
    check("open", v is not None)
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
        with screen.render() as r:
            r.fill((24, 26, 34))
            if f is not None:
                pygame.gfxdraw.draw_surface(r, f)
            hud = font.render(
                f"pos={v.position():.2f}s frames={frames} audio={v.has_audio()}", True,
                (200, 205, 215))
            pygame.gfxdraw.set_transform(r, pygame.math.mat4_translation(-460, 250, 0))
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

    for m in (f"frames={frames}", f"has_audio={v.has_audio()}"):
        print("[INFO]", m)
    print(f"[SUMMARY] PASS={len(PASS)} FAIL={len(FAIL)} {FAIL or ''}")
    last = time.time()
    while True:
        for e in pygame.event.get():
            if e.type == pygame.event.QUIT:
                return
            if e.type == pygame.event.KEYDOWN and e.key == pygame.key.K_ESCAPE:
                return
        if time.time() - last > 2.0:
            return
        with screen.render() as r:
            r.fill((24, 26, 34))
            y = 30
            for line in PASS + FAIL:
                s = font.render(line, True, (140, 220, 140) if line in PASS else (230, 120, 120))
                pygame.gfxdraw.set_transform(r, pygame.math.mat4_translation(-440, y, 0))
                pygame.gfxdraw.draw_surface(r, s)
                y += 26
        pygame.display.flip()
        await pygame.next_frame()
