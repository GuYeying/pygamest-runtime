# egui_input —— runtime 形态 IME 链端到端验证（egui text_edit + 原始
# textinput 双通道回显；隐式软键盘跟 egui 焦点走——零脚本调用）。
# 退出：返回键 / ESC。
import pygame
import pygame_gui as egui


class Hud(egui.UiBase):
    def __init__(self):
        super().__init__()
        self.name = "点我打字"
        self.raw_n = 0
        self.last_raw = "-"
        self.kb = False

    def draw(self, ui):
        ui.heading("IME + egui 输入框验证")
        self.name = ui.text_edit(self.name)
        ui.label(f"输入框内容 = {self.name}")
        ui.label(f"原始 textinput n={self.raw_n} last={self.last_raw}")
        ui.label(f"键盘弹出 = {self.kb}")


async def main():
    screen = pygame.display.set_mode((800, 600))
    egui.init()
    hud = Hud()

    while True:
        for e in pygame.event.get():
            if e.type == pygame.event.QUIT:
                return
            if e.type == pygame.event.KEYDOWN and e.key == pygame.key.K_ESCAPE:
                return
            if e.type == "textinput":
                hud.raw_n += 1
                hud.last_raw = e.text
            egui.event(e)

        with screen.render() as r:
            r.fill((24, 26, 34))
            r.draw_ui(hud)

        pygame.display.flip()
        await pygame.next_frame()
