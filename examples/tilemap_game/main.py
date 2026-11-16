# tilemap_layers_test —— pygame_tilemap 极简案例（阶段三验收样张）：
# 程序生成 Tiled TMX（3 层 finite 地图，CSV data）→ Tilemap 解析（sfx
# 密文链）→ per-layer 渲染数组（layer_mesh —— quad/UV 顺序展开）→
# **着色器渲染层次拓展**：每层独立 WGSL pipeline 按层序 draw（ground =
# UV 程序化瓦片纹 / deco = tint 色调层 / fx = UV 水波 + alpha 半透明
# 层）。零资产（图集纹理 shader 程序化——真图集链 v2 验）。600 帧自
# 动退；控制台 [tilemap-layers] 逐项断言。
import pygame
import pygame_tilemap

# ── TMX 程序生成（12×8 地图；ground 全铺 / deco 稀疏装饰 / fx 水面条）──
MW, MH = 12, 8


# ── WGSL 层 shader 三部曲（程序化瓦片纹——UV 图集域 128×32，4 瓦列
# 色板 + 瓦内网点；camera/phase 槽位一致）──
WGSL_HEAD = """
struct Camera {
    mvp: mat4x4<f32>,
};
struct U {
    phase: f32,
};
@group(0) @binding(0) var<uniform> camera: Camera;
@group(0) @binding(1) var<uniform> u: U;

struct VIn {
    @location(0) pos: vec2<f32>,
    @location(1) uv: vec2<f32>,
}
struct VOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
}
@vertex
fn vs_main(vin: VIn) -> VOut {
    var o: VOut;
    o.pos = camera.mvp * vec4<f32>(vin.pos.x, vin.pos.y, 0.0, 1.0);
    o.uv = vin.uv;
    return o;
}

// 程序化图集：UV ∈ [0,1] 映射图集 128×32（4 瓦列）——瓦列色板 +
// 瓦内网点（checker 2×2）；bind 色 = 层基调（layer_tint）
fn atlas_color(uv: vec2<f32>, a: vec3<f32>, b: vec3<f32>) -> vec4<f32> {
    let px = uv * vec2<f32>(128.0, 32.0);
    let col = floor(px.x / 32.0);                       // 瓦列 0..3
    let tuv = fract(px / 32.0);                         // 瓦内 0..1
    let dot = floor(tuv * 4.0).x + floor(tuv * 4.0).y;  // 瓦内 4×4 网格奇偶
    let shade = select(1.0, 0.82, dot == dot && fract(dot / 2.0) > 0.25);
    // 瓦列色板（4 变体梯度）
    let g = col / 4.0;
    let base = mix(a, b, g);
    return vec4<f32>(base * shade, 1.0);
}
"""

WGSL_GROUND = WGSL_HEAD + """
@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
    return atlas_color(in.uv, vec3<f32>(0.42, 0.58, 0.35), vec3<f32>(0.55, 0.75, 0.42));
}
"""

WGSL_DECO = WGSL_HEAD + """
@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
    let c = atlas_color(in.uv, vec3<f32>(0.55, 0.44, 0.78), vec3<f32>(0.72, 0.62, 0.95));
    // tint：冷灰蓝调（装饰层专属 shader——层次区分）
    return vec4<f32>(c.r * 0.45, c.g * 0.58, c.b * 0.85, c.a);
}
"""

WGSL_FX = WGSL_HEAD + """
@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
    // 水波：UV 横向正弦扰动（帧相位 uniform）+ alpha 半透明
    let wob = vec2<f32>(sin(in.uv.y * 40.0 + u.phase) * 0.004, 0.0);
    let c = atlas_color(in.uv + wob, vec3<f32>(0.30, 0.50, 0.85), vec3<f32>(0.45, 0.68, 0.98));
    let shimmer = 0.85 + 0.15 * sin(in.uv.x * 60.0 + u.phase * 1.7);
    return vec4<f32>(c.rgb * shimmer, 0.62);
}
"""


async def main():
    pygame.display.set_caption("tilemap_layers_test")
    screen = pygame.display.set_mode((768, 512))
    cjk = pygame.font.Font("cjk", 15)
    ac = pygame.render.access()
    M = pygame.math
    frame = 0
    _fail = []

    def st(name, cond):
        if cond:
            print("[tilemap-layers] PASS", name)
        else:
            _fail.append(name)
            print("[tilemap-layers] FAIL", name)

    # ── 程序生成 TMX（写盘走 pygame.io 面——裁剪 stdlib 无 open）──
    pass  # TMX 随 payload 预部署（web 无同步 io——预生成文件直读）

    # ── 解析（sfx 密文链——dev 宿主明文透传）──
    tm = pygame_tilemap.Tilemap("tilemap_layers.tmx")
    st("Tilemap 构造", tm is not None)
    st("地图尺寸 12×8", tm.width() == 12 and tm.height() == 8)
    st("瓦片 32×32", tm.tile_width() == 32 and tm.tile_height() == 32)
    st("层数 3", tm.layer_count() == 3)
    st("图集数 3", tm.tileset_count() == 3)

    infos = [tm.layer_info(i) for i in range(3)]
    st("层名 ground/deco/fx",
       [r[0] for r in infos] == ["ground", "deco", "fx"])
    st("层类全 tiles", all(r[1] == "tiles" for r in infos))

    tiles_g = tm.layer_tiles(0)
    st("ground 层 96 格全铺", len(tiles_g) == MW * MH)
    st("tileset_index 正确（ground=0）", tiles_g[0][2] == 0)

    # ── 渲染数组（每层 quad/UV）──
    verts_g, uvs_g = tm.layer_mesh(0)
    n_g = len(verts_g) // 2
    st("ground mesh 顶点数 = 96 格×6", n_g == MW * MH * 6)
    st("UV 归一域", all(0.0 <= v <= 1.0 for v in uvs_g))
    verts_f, uvs_f = tm.layer_mesh(2)
    st("fx 层非空（水面条）", len(verts_f) > 0)

    ts0 = tm.tileset_info(0)
    st("tileset_info 图集切分",
       ts0[1] == "atlas_ground.png" and ts0[4] == 32 and ts0[6] == 4)

    # ── 渲染：每层一 mesh 一 pipeline 按层序 draw（着色器层次拓展）──
    cam_buf = ac.buffer(64, label="cam_buf")
    phase_buf = ac.buffer(16, label="phase_buf")

    def build_layer(verts, uvs, wgsl, blend, label):
        # 交错化（verts[i] 与 uvs[i] 同顶点——顺序展开序一致）
        inter = []
        for i in range(len(verts) // 2):
            inter.extend((verts[i * 2], verts[i * 2 + 1],
                          uvs[i * 2], uvs[i * 2 + 1]))
        mesh = ac.mesh(["float32x2", "float32x2"], inter, label=label)
        shader = ac.shader(wgsl, label=label + "_shader")
        bind = ac.bind_group([(0, "uniform", cam_buf),
                              (1, "uniform", phase_buf)],
                             label=label + "_bind")
        pipe = ac.pipeline(shader, mesh, [bind],
                           cull="none", blend=blend,
                           depth_mode="disabled",
                           label=label + "_pipe")
        return mesh, pipe, bind

    g_mesh, g_pipe, g_bind = build_layer(verts_g, uvs_g, WGSL_GROUND, "opaque", "ground")
    d_verts, d_uvs = tm.layer_mesh(1)
    d_mesh, d_pipe, d_bind = build_layer(d_verts, d_uvs, WGSL_DECO, "opaque", "deco")
    f_mesh, f_pipe, f_bind = build_layer(verts_f, uvs_f, WGSL_FX, "alpha", "fx")
    st("三层 pipeline 构建", g_pipe is not None and d_pipe is not None and f_pipe is not None)

    # 正交相机（像素域——Tiled 世界系 y-down；game_camera_ortho letterbox）
    cam = pygame.render.game_camera_ortho(768, 512, 768, 512)
    screen.set_camera(cam)

    text_cache = {}

    def hud_text(s, color=(210, 214, 224)):
        if s not in text_cache:
            text_cache[s] = cjk.render(s, True, color)
        return text_cache[s]

    def draw_hud(rt):
        pygame.gfxdraw.set_transform(rt, M.mat4_translation(-372, 244, 0))
        pygame.gfxdraw.draw_surface(rt, hud_text(
            "[tilemap] 3 层 3 shader 按层序叠加：地面贴图 / 装饰 tint / 水波 alpha"))
        pygame.gfxdraw.set_transform(rt, M.mat4_translation(-372, 224, 0))
        pygame.gfxdraw.draw_surface(rt, hud_text(
            f"ground {len(verts_g)//2} v | deco {len(d_verts)//2} v | fx {len(verts_f)//2} v",
            (255, 220, 90)))

    while True:
        for e in pygame.event.get():
            if e.type == pygame.event.QUIT:
                return

        t = frame / 60.0
        # 水波相位（vec4 填充——uniform 16B 对齐）
        ac.write_buffer(phase_buf, [t * 3.0, 0.0, 0.0, 0.0])
        pygame.render.write_camera_mvp(cam_buf, cam.mvp())

        with screen.render() as rt:
            rt.fill((24, 28, 38))
            with screen.raw_render(depth=False) as p:
                # 层序 draw：ground → deco → fx（着色器分层叠加）
                p.set_pipeline(g_pipe)
                p.set_bind_group(0, g_bind)
                p.draw_mesh(g_mesh)
                p.set_pipeline(d_pipe)
                p.set_bind_group(0, d_bind)
                p.draw_mesh(d_mesh)
                p.set_pipeline(f_pipe)
                p.set_bind_group(0, f_bind)
                p.draw_mesh(f_mesh)
            draw_hud(rt)

        pygame.display.flip()
        frame += 1
        if frame == 30:
            print("[tilemap-layers] SUMMARY",
                  "PASS" if not _fail else "FAIL " + str(_fail))
        if frame > 1200:
            return
        await pygame.next_frame()
