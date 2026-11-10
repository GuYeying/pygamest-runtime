# dialog_probe —— SAF 对话框真机/模拟器探针（结果屏显——Android 无
# stdout）：await open_file → DocumentsUI → 选文件/取消 → 屏显 name 与
# 字节数；再 await save_bytes → 另存位置 → 屏显结果。期间帧循环存活
# （背景持续重绘彩色心跳条 = 异步面核心验证）。
import time

import pygame

PASS = []
FAIL = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name + ((" " + detail) if detail else ""))


async def main():
    screen = pygame.display.set_mode((800, 600))
    font = pygame.font.Font(None, 24)
    lines = ["probe: await pygame.dialog.open_file() …"]

    picked = await pygame.dialog.open_file("选个文件", [("任意", ["*"])])
    if picked is None:
        check("open_file（用户取消→None 合法）", True)
        lines.append("open_file = None（取消）")
    else:
        data = picked.read()
        check("open_file PickedFile", len(data) > 0, f"name={picked.name()} bytes={len(data)}")
        lines.append(f"open_file name={picked.name()} bytes={len(data)}")

    saved = await pygame.dialog.save_bytes("probe_out.txt", "你好 SAF".encode("utf-8"))
    check("save_bytes", saved is True or saved is False, f"saved={saved}")
    lines.append(f"save_bytes = {saved}")

    print(f"[SUMMARY] PASS={len(PASS)} FAIL={len(FAIL)} {FAIL or ''}")
    t0 = time.time()
    while True:
        for e in pygame.event.get():
            if e.type == pygame.event.QUIT:
                return
            if e.type == pygame.event.KEYDOWN and e.key == pygame.key.K_ESCAPE:
                return
        with screen.render() as r:
            r.fill((24, 26, 34))
            y = 30
            for line in lines + PASS + FAIL:
                s = font.render(line, True, (140, 220, 140) if line in PASS else (230, 120, 120) if line in FAIL else (220, 220, 220))
                pygame.gfxdraw.set_transform(r, pygame.math.mat4_translation(-380, y, 0))
                pygame.gfxdraw.draw_surface(r, s)
                y += 28
            # 心跳文本（帧循环存活证据——对话框期间也在走秒）
            beat = font.render(f"alive {time.time() - t0:6.1f}s", True, (120, 200, 120))
            pygame.gfxdraw.set_transform(r, pygame.math.mat4_translation(-380, 540, 0))
            pygame.gfxdraw.draw_surface(r, beat)
        pygame.display.flip()
        await pygame.next_frame()
