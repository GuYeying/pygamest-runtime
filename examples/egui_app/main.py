# window_mode_test —— 显示模式运行时切换案例（手机设备测试定向）：
# egui 单选（互斥复选框组）四种显示模式——竖屏比例 / 横屏比例 /
# 横全屏 / 竖全屏；运行时重 set_mode（display 可重开语义）。
# 手机上物理 surface 恒全屏——四种模式呈现为 letterbox 画布比例差异
# （竖屏比例 = 9:16 画布居中、横屏比例 = 16:9 满宽、全屏旗标在手机面
# 为 no-op）；桌面 = 真窗口/全屏切换。画布边界框 + 中心十字可视化。
# 退出：ESC / 关窗（全屏下 ESC 退出）。
import pygame
import pygame_gui as egui

MODES = [
    ("竖屏比例", (450, 800), 0, "portrait"),
    ("横屏比例", (800, 450), 0, "landscape"),
    ("横全屏", (0, 0), pygame.display.FULLSCREEN, "landscape"),
    ("竖全屏", (450, 800), pygame.display.FULLSCREEN, "portrait"),
]


class HUD(egui.UiBase):
    """单选模式面板（互斥复选框组）+ 模式信息。切换经 want 由主循环消费。"""

    def __init__(self):
        self.mode = 1            # 起始：横屏比例
        self.want = -1           # >=0 = 主循环应用
        self.info = ""
        self.name = "玩家"
        
    def draw(self, ui):
        ui.heading("显示模式（单选）")
        for i, (name, _, _, _o) in enumerate(MODES):
            checked = ui.checkbox(name, self.mode == i)
            if checked and self.mode != i:
                self.want = i
                self.mode = i
        ui.separator()
        ui.label(self.info)
        ui.label("手机：物理面恒全屏 = 画布比例差异（letterbox）")
        self.name = ui.text_edit(self.name)


async def main():
    pygame.display.set_caption("window_mode_test")
    egui.init()
    screen = pygame.display.set_mode((800, 450))
    hud = HUD()
    applied = 1
    frame = 0

    while True:
        for e in pygame.event.get():
            if e.type == pygame.event.QUIT:
                return
            if e.type == pygame.event.KEYDOWN and e.key == pygame.key.K_ESCAPE:
                return
            egui.event(e)   

        # 应用模式切换（会话块外——display 可重开语义）
        if hud.want >= 0:
            name, size, flags, orient = MODES[hud.want]
            # 方向先行（Activity 级旋转——表面尺寸随后变化；嵌入宿主
            # configChanges 含 orientation = 只重表面不重建 Activity）
            try:
                pygame.display.set_orientation(orient)
            except Exception as ex:
                print("[wm] set_orientation:", ex)
            if flags:
                screen = pygame.display.set_mode(size, [flags])
            else:
                screen = pygame.display.set_mode(size)
            applied = hud.want
            hud.want = -1

        with screen.render() as t:
            t.fill((16, 18, 26))

            # 画布边界框 + 中心十字（letterbox 可视化）
            w, h = screen.get_size()
            pygame.gfxdraw.set_color(t, (90, 200, 120))
            pygame.gfxdraw.rectangle(t, (-w // 2, -h // 2, w, h))
            pygame.gfxdraw.line(t, -40, 0, 40, 0)
            pygame.gfxdraw.line(t, 0, -40, 0, 40)
            # 四角标记（画布四角一眼可辨）
            for cx in (-w // 2, w // 2 - 20):
                for cy in (-h // 2, h // 2 - 20):
                    pygame.gfxdraw.box(t, (cx, cy, 20, 20))

            # 信息面板
            name = MODES[applied][0]
            phys = pygame.render.screen_size()
            hud.info = f"mode={name}  logical={w}x{h}  physical={phys[0]}x{phys[1]}"
            t.draw_ui(hud)

        pygame.display.flip()
        pygame.time.delay(8)
        frame += 1
        await pygame.next_frame()
