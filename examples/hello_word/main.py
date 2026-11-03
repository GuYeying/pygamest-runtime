
import pygame

async def main():

    screen = pygame.display.set_mode((800, 600))
    font   = pygame.font.Font(None, 32)

    hello_world_text = font.render("Hello Word!", True, (255, 255, 255))

    clock = pygame.time.Clock()

    image = await pygame.image.load("assets/ferris.png")
    sound = await pygame.mixer.load("assets/bleep.wav")

    _ch = pygame.mixer.Channel(0)
    pygame.mixer.set_reserved(1)
    _fx = pygame.mixer.Effect("gain")
    _fx.set("gain", 0.5)
    _ch.add_effect(_fx)
    _ch.play(sound,50)

    while True:
        for e in pygame.event.get():
            if e.type == pygame.event.QUIT:
                return
            if e.type == pygame.event.KEYDOWN and e.key == pygame.key.K_ESCAPE:
                return

        with screen.render() as r:
            r.fill((125,125,125))
            r.blit(image,(0,0))
            r.blit(hello_world_text, (325, 275))

        clock.tick(60)

        pygame.display.flip()

        await pygame.next_frame()

































#你绷住了么，hello word比hello world可有创意了！