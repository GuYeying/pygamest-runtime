import pygame

async def main():
    screen = pygame.display.set_mode((800, 600))
    font = pygame.font.Font(None, 32)
    text = font.render("Hello Word!", True, (255, 255, 255))

    clock = pygame.time.Clock()

    image = await pygame.image.load("assets/ferris.png")
    sound = await pygame.mixer.load("assets/bleep.wav")

    _ch = pygame.mixer.Channel(0)
    pygame.mixer.set_reserved(1)
    _fx = pygame.mixer.Effect("gain")
    _fx.set("gain", 0.5)
    _ch.add_effect(_fx)
    _ch.play(sound, 50)

    while True:
        for e in pygame.event.get():
            if e.type == pygame.event.QUIT:
                return
            if e.type == pygame.event.KEYDOWN and e.key == pygame.key.K_ESCAPE:
                return

        with screen.render() as r:
            r.fill((125, 125, 125))
            # 图片居中（draw_surface 中心锚：局部原点 = 物体中心）
            pygame.gfxdraw.set_transform(r, pygame.math.mat4_translation(0, 0, 0))
            pygame.gfxdraw.draw_surface(r, image)
            # 文字放图片上方
            pygame.gfxdraw.set_transform(r, pygame.math.mat4_translation(0, 200, 0))
            pygame.gfxdraw.draw_surface(r, text)

        clock.tick(60)
        pygame.display.flip()
        await pygame.next_frame()


# 你绷住了么，hello word 比 hello world 可有创意了！
