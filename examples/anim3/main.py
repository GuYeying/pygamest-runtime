# anim3 —— 三动画库联合 demo（打包验证形态）：spine 左 · live2d 中 ·
# ozz 右，一屏三模型同帧驱动。退出：ESC / 关窗。
import time

import pygame
import pygame_live2d
import pygame_ozz
import pygame_spine


async def main():
    screen = pygame.display.set_mode((1280, 720))
    font = pygame.font.Font(None, 26)
    hud = font.render("anim3: spine | live2d | ozz  (ESC quit)", True, (200, 205, 215))

    # ── spine（左：spineboy walk）──
    data, pages = pygame_spine.load_with_atlas(
        "assets/spineboy/spineboy-ess.json", "assets/spineboy/spineboy.atlas")
    sk = pygame_spine.Skeleton(data)
    sk.set_skin("default")
    anim = data.find_animation("walk")
    state = pygame_spine.AnimationState()
    state.set_animation(anim, True)
    page0 = await pygame.image.load("assets/spineboy/spineboy.png")

    # ── live2d（中：Hiyori + idle motion）──
    rt = pygame_live2d.load_runtime("assets/models/Hiyori/Hiyori.model3.json")
    motion = pygame_live2d.load_motion("assets/models/Hiyori/motions/Hiyori_m01.motion3.json")
    player = pygame_live2d.motion_player(motion)
    buf = pygame.Surface((430, 560))

    # ── ozz（右：骨骼线 + 关节盒体）──
    p3 = pygame_ozz.OzzPlayer("assets/skeleton.ozz", "assets/animation.ozz")
    dur = p3.duration()

    hud_tf = pygame.math.mat4_translation(-560, 320, 0)
    spine_tf = pygame.math.mat4_translation(-430, -40, 0).mul_mat4(
        pygame.math.mat4_scale(0.55, 0.55, 0.55))
    l2d_tf = pygame.math.mat4_translation(-215, 60, 0)

    last = time.time()
    t = 0.0
    while True:
        for e in pygame.event.get():
            if e.type == pygame.event.QUIT:
                return
            if e.type == pygame.event.KEYDOWN and e.key == pygame.key.K_ESCAPE:
                return
        now = time.time()
        dt = now - last
        last = now
        t += dt

        # spine 步进
        state.update(dt)
        state.apply(sk)
        sk.update_world_transform()
        # live2d 步进（motion 驱动参数）
        player.tick(dt)
        player.apply(rt)
        rt.update_meshes()
        # ozz 步进（ratio 循环采样）
        p3.sample((t % dur) / dur)

        with screen.render() as r:
            r.fill((24, 26, 34))
            # spine（左）
            pygame.gfxdraw.set_transform(r, spine_tf)
            pygame.gfxdraw.draw_spine(r, sk, [page0])
            # live2d（中：全管线自理进产物面，再上屏）
            rt.draw(buf, x=0.0, y=0.05, scale=0.92)
            pygame.gfxdraw.set_transform(r, l2d_tf)
            pygame.gfxdraw.draw_surface(r, buf)
            # ozz（右：骨骼 + 关节）
            pygame.gfxdraw.set_transform(r, pygame.math.mat4_translation(0, 0, 0))
            pygame.gfxdraw.draw_ozz_quads(r, p3, scale=95.0, cx=430, cy=-60, size=14.0)
            pygame.gfxdraw.draw_ozz_bones(r, p3, scale=95.0, cx=430, cy=-60)
            # HUD
            pygame.gfxdraw.set_transform(r, hud_tf)
            pygame.gfxdraw.draw_surface(r, hud)
        pygame.display.flip()
        await pygame.next_frame()
