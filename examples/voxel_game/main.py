# voxel_mc_test —— pygame_voxelis 极简 MC 案例（阶段二验收样张，
# 2026-11-16 优化版）：
# 稀疏体素地形（VoxWorld 16×16×16 体素/chunk，体素 1.0）+ rapier3d
# 体素物理（表面 cuboid + 动态方块发射）+ 射线选择（cast_ray 命中 →
# 删除/放置）+ mesh_builder 法线光照渲染。
# 优化四点：① GameCamera 显式相机接入（perspective + set_camera 定约
# ——MVP 经 cam.mvp() 内聚 letterbox 直喂 uniform，免 write_camera_mvp
# 的 fit 双乘）② 球渲染/物理尺寸对齐（mesh scale = 2×collider half
# ——修复"碰撞体积与渲染网格大小不符"）③ 单块顶点语义 probe（mesh
# 世界盒 [x,x+1] ≡ collider 盒——证词打点）④ 删除顶层后的露层 collider
# 增量补挂（消除"mesh 有块物理穿"）。
# 交互：鼠标拖拽转向 / WASD-QE 漫游 / 左键删 / 右键放 / F 发射方块 /
# R 重建地形 / ESC 退出。控制台 [voxel-mc] 打点逐项验证。
import pygame
import pygame_voxelis
import pygame_physics as rp3

# 三角函数面 = pygame.math 模块属性（import 子模块需 __path__ 不可用；
# 属性直取——模块级供 fps_view 等顶层函数引用）
M = pygame.math

# WGSL：顶点 = pos3 + normal3；片元 = 法线光照 + 世界坐标程序染色
# （顶面草绿 checker / 侧面土棕——体素值染色走扩展 attribute，v2 再接）
WGSL_VOXEL = """
struct Camera {
    mvp: mat4x4<f32>,
};

@group(0) @binding(0) var<uniform> camera: Camera;

struct VIn {
    @location(0) pos: vec3<f32>,
    @location(1) nrm: vec3<f32>,
}

struct VOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) world: vec3<f32>,
    @location(1) normal: vec3<f32>,
}

@vertex
fn vs_main(vin: VIn) -> VOut {
    var o: VOut;
    o.pos = camera.mvp * vec4<f32>(vin.pos, 1.0);
    o.world = vin.pos;
    o.normal = vin.nrm;
    return o;
}

@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
    // 程序染色：顶面草绿 checker（floor(x)+floor(z) 奇偶），侧面土棕
    let checker = (floor(in.world.x) + floor(in.world.z)) % 2.0;
    var base = vec3<f32>(0.55, 0.38, 0.22);   // 土棕（侧面）
    if (in.normal.y > 0.5) {
        base = mix(vec3<f32>(0.30, 0.62, 0.20), vec3<f32>(0.42, 0.74, 0.26), checker);
    } else if (in.normal.y < -0.5) {
        base = vec3<f32>(0.30, 0.24, 0.18);   // 底面暗土
    }
    // 法线漫反射 + 环境光
    let light_dir = normalize(vec3<f32>(0.5, 0.9, 0.35));
    let ndotl = max(dot(in.normal, light_dir), 0.0);
    let brightness = 0.30 + 0.70 * ndotl;
    return vec4<f32>(base * brightness, 1.0);
}
"""

# 发射方块 WGSL（model 矩阵 per-frame 更新——平移自物理查询回填）
WGSL_CUBE = """
struct Camera {
    mvp: mat4x4<f32>,
};
struct Model {
    model: mat4x4<f32>,
};

@group(0) @binding(0) var<uniform> camera: Camera;
@group(0) @binding(1) var<uniform> model: Model;

struct VIn {
    @location(0) pos: vec3<f32>,
    @location(1) nrm: vec3<f32>,
}

struct VOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) normal: vec3<f32>,
}

@vertex
fn vs_main(vin: VIn) -> VOut {
    var o: VOut;
    let wp = model.model * vec4<f32>(vin.pos, 1.0);
    o.pos = camera.mvp * wp;
    o.normal = normalize((model.model * vec4<f32>(vin.nrm, 0.0)).xyz);
    return o;
}

@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
    let light_dir = normalize(vec3<f32>(0.5, 0.9, 0.35));
    let ndotl = max(dot(in.normal, light_dir), 0.0);
    let brightness = 0.35 + 0.65 * ndotl;
    return vec4<f32>(vec3<f32>(0.85, 0.55, 0.15) * brightness, 1.0);
}
"""

# 小立方体顶点（pos3+normal3 顺序展开 36 顶点；±0.5 = 单位 1.0 宽
# ——发射方块 collider half=0.5，渲染 scale 1.0 即物理一致）
CUBE_VERTS = [
    # 前 +z
    -0.5, -0.5,  0.5,  0, 0, 1,   0.5, -0.5,  0.5,  0, 0, 1,   0.5, 0.5,  0.5,  0, 0, 1,
    -0.5, -0.5,  0.5,  0, 0, 1,   0.5,  0.5,  0.5,  0, 0, 1,  -0.5,  0.5,  0.5,  0, 0, 1,
    # 后 -z
     0.5, -0.5, -0.5,  0, 0,-1,  -0.5, -0.5, -0.5,  0, 0,-1,  -0.5,  0.5, -0.5,  0, 0,-1,
     0.5, -0.5, -0.5,  0, 0,-1,  -0.5,  0.5, -0.5,  0, 0,-1,   0.5,  0.5, -0.5,  0, 0,-1,
    # 右 +x
     0.5, -0.5,  0.5,  1, 0, 0,   0.5, -0.5, -0.5,  1, 0, 0,   0.5,  0.5, -0.5,  1, 0, 0,
     0.5, -0.5,  0.5,  1, 0, 0,   0.5,  0.5, -0.5,  1, 0, 0,   0.5,  0.5,  0.5,  1, 0, 0,
    # 左 -x
    -0.5, -0.5, -0.5, -1, 0, 0,  -0.5, -0.5,  0.5, -1, 0, 0,  -0.5,  0.5,  0.5, -1, 0, 0,
    -0.5, -0.5, -0.5, -1, 0, 0,  -0.5,  0.5,  0.5, -1, 0, 0,  -0.5,  0.5, -0.5, -1, 0, 0,
    # 上 +y
    -0.5,  0.5,  0.5,  0, 1, 0,   0.5,  0.5,  0.5,  0, 1, 0,   0.5,  0.5, -0.5,  0, 1, 0,
    -0.5,  0.5,  0.5,  0, 1, 0,   0.5,  0.5, -0.5,  0, 1, 0,  -0.5,  0.5, -0.5,  0, 1, 0,
    # 下 -y
    -0.5, -0.5,  0.5,  0,-1, 0,  -0.5, -0.5, -0.5,  0,-1, 0,   0.5, -0.5, -0.5,  0,-1, 0,
    -0.5, -0.5,  0.5,  0,-1, 0,   0.5, -0.5, -0.5,  0,-1, 0,   0.5, -0.5,  0.5,  0,-1, 0,
]

# FPS view 矩阵（手写 look_at——yaw/pitch 驱动；返回 Mat4 直配 GameCamera
# with_view；三角取 pygame.math 模块函数——裁剪版 stdlib 无 math）
def fps_view(eye, yaw_deg, pitch_deg):
    yaw = M.radians(yaw_deg)
    pitch = M.radians(pitch_deg)
    fx = M.cos(pitch) * M.sin(yaw)
    fy = M.sin(pitch)
    fz = -M.cos(pitch) * M.cos(yaw)
    f = (fx, fy, fz)                       # 前向
    up0 = (0.0, 1.0, 0.0)
    s = (fy * up0[2] - fz * up0[1],
         fz * up0[0] - fx * up0[2],
         fx * up0[1] - fy * up0[0])        # right = f × up
    u = (s[1] * fz - s[2] * fx,
         s[2] * fx - s[0] * fz,
         s[0] * fy - s[1] * fx)            # true up = s × f
    ex, ey, ez = eye
    # 视图基（行主视觉——标准 view 行向量）→ 列主展开（from_cols_array
    # 列主序契约：out[c*4+r] = m[r*4+c]）
    m = [
        s[0], s[1], s[2], -s[0] * ex - s[1] * ey - s[2] * ez,
        u[0], u[1], u[2], -u[0] * ex - u[1] * ey - u[2] * ez,
        -f[0], -f[1], -f[2], f[0] * ex + f[1] * ey + f[2] * ez,
        0.0, 0.0, 0.0, 1.0,
    ]
    cols = [m[r * 4 + c] for c in range(4) for r in range(4)]
    return M.mat4_from_cols_array(cols)


async def main():
    pygame.display.set_caption("voxel_mc_test")
    screen = pygame.display.set_mode((1024, 640))
    cjk = pygame.font.Font("cjk", 15)
    ac = pygame.render.access()
    frame = 0
    _fail = []

    def st(name, cond):
        if cond:
            print("[voxel-mc] PASS", name)
        else:
            _fail.append(name)
            print("[voxel-mc] FAIL", name)

    # ── 体素世界（16³/chunk，体素 1.0）+ 地形 ──
    vw = pygame_voxelis.VoxWorld(4, 16.0)
    st("VoxWorld 构造", vw is not None)
    st("voxel_size 换算", abs(vw.voxel_size() - 1.0) < 1e-5)

    # ── 单块顶点语义 probe（碰撞对齐证词）：体素 (0,0,0) 世界盒 =
    # [0,1]³ ≡ collider（中心 +0.5、half 0.5）——绑定层公式 chunk
    # offset + CUBE ±half_voxel + 0.5 中心偏移的落地验证 ──
    probe = pygame_voxelis.VoxWorld(4, 16.0)
    probe.set_voxel(0, 0, 0, 1)
    pv, _pn, _pi = probe.generate_mesh()
    pmin = (min(pv[0::3]), min(pv[1::3]), min(pv[2::3]))
    pmax = (max(pv[0::3]), max(pv[1::3]), max(pv[2::3]))
    ok = (abs(pmin[0]) < 1e-4 and abs(pmin[1]) < 1e-4 and abs(pmin[2]) < 1e-4
          and abs(pmax[0] - 1.0) < 1e-4 and abs(pmax[1] - 1.0) < 1e-4
          and abs(pmax[2] - 1.0) < 1e-4)
    st(f"单块 mesh 盒 {tuple(round(x,3) for x in pmin)}..{tuple(round(x,3) for x in pmax)} ≡ collider [0,1]³", ok)

    height = [[4 + int(2.0 * M.sin(x * 0.4) * M.cos(z * 0.3))
               for z in range(16)] for x in range(16)]

    def build_terrain():
        for x in range(16):
            for z in range(16):
                h = height[x][z]
                for y in range(h):
                    vw.set_voxel(x, y, z, 1)
        vw.set_voxel(3, height[3][3], 3, 2)     # 石块样本（值区分存证）
        vw.set_voxel(5, height[5][5], 5, 2)

    build_terrain()
    # chunk_count 宽松断言（VoxModel::new 预建 world_bounds 网格——
    # 32³ 全量 chunk 表，非稀疏指标；≥1 = 至少根 chunk 存在）
    st("地形写入后 chunk_count>=1", vw.chunk_count() >= 1)
    st("get_voxel 读回", vw.get_voxel(3, height[3][3], 3) == 2)
    st("get_voxel 空 = None", vw.get_voxel(100, 100, 100) is None)

    # ── 物理（表面体素 cuboid + 射线选择）──
    world = rp3.PhysicsWorld3D(gravity=(0, -9.81, 0))
    col_bodies = {}                          # (x,y,z) → body handle（表面块+放置块）
    # add_collider(key)：增量 collider（表面块/放置块/露层补挂共用——
    # 中心 +0.5 half 0.5 ≡ mesh 世界盒 [x,x+1]，渲染物理对齐）
    def add_collider(key):
        x, y, z = key
        b = rp3.RigidBodyBuilder3D("fixed",
                                   translation=(x + 0.5, y + 0.5, z + 0.5))
        c = rp3.ColliderBuilder3D("cuboid", hx=0.5, hy=0.5, hz=0.5, friction=0.8)
        col_bodies[key] = world.insert(b, c)[0]

    for x in range(16):
        for z in range(16):
            h = height[x][z]
            add_collider((x, h - 1, z))      # 每列顶层块（内部块打不到）

    # 时序契约：insert 后须至少 step 一次方可 cast_ray（broad_phase 时序）
    world.step_frame(1.0 / 60.0)
    hit = world.cast_ray((8.0, 8.0, 8.0), (0.0, -1.0, 0.0), None)
    st("cast_ray 命中地面", hit is not None and hit[1] > 0.0)

    # ── 相机（GameCamera 显式定约——perspective letterbox 内聚）──
    eye = [8.0, 9.0, 22.0]
    yaw, pitch = 0.0, -12.0
    cam = pygame.render.game_camera_perspective(
        58.0, 1024, 640, 1024, 640, 0.1, 300.0)
    screen.set_camera(cam)                   # 会话级显式相机（空档自动面）
    cam_buf = ac.buffer(64, label="cam_buf")
    model_buf = ac.buffer(64, label="model_buf")

    # ── 体素 mesh（voxelis 数组出口 → mesh_builder）──
    voxel_shader = ac.shader(WGSL_VOXEL, label="voxel_shader")
    cube_shader = ac.shader(WGSL_CUBE, label="ball_shader")
    vox_pipe = [None]   # 体素 pipeline + bind（交互重建时一并换新）
    vox_bind = [None]

    def rebuild_voxel_mesh():
        verts, norms, idx = vw.generate_mesh()
        # 顺序展开（indices → 顶点流；案例级规模免 index 管线）
        expanded = []
        for i in idx:
            v = (verts[i * 3], verts[i * 3 + 1], verts[i * 3 + 2])
            n = (norms[i * 3], norms[i * 3 + 1], norms[i * 3 + 2])
            expanded.extend(v)
            expanded.extend(n)
        mesh = ac.mesh(["float32x3", "float32x3"], expanded, label="voxel_mesh")
        bind = ac.bind_group([(0, "uniform", cam_buf)], label="voxel_bind")
        vox_bind[0] = bind
        vox_pipe[0] = ac.pipeline(voxel_shader, mesh, [bind],
                                  cull="back", blend="opaque",
                                  depth_mode="standard", depth_write=True,
                                  label="voxel_pipe")
        return mesh, len(idx) // 3

    vox_mesh, tri_count = rebuild_voxel_mesh()
    st("generate_mesh 出口", tri_count > 0)
    print(f"[voxel-mc] 地形 mesh：{tri_count} 三角形")

    # ── 发射方块（动态立方体——collider half 0.5 ≡ 渲染 scale 1.0，
    # 尺寸严格对齐；物理验证核心样张）──
    ball_mesh = ac.mesh(["float32x3", "float32x3"], CUBE_VERTS, label="ball_mesh")
    ball_bind = ac.bind_group([
        (0, "uniform", cam_buf),
        (1, "uniform", model_buf),
    ], label="ball_bind")
    ball_pipe = ac.pipeline(cube_shader, ball_mesh, [ball_bind],
                            cull="back", blend="opaque",
                            depth_mode="standard", depth_write=True,
                            label="ball_pipe")
    balls = []                               # body handle 流

    def launch_ball():
        yaw_r = M.radians(yaw)
        pitch_r = M.radians(pitch)
        d = (M.cos(pitch_r) * M.sin(yaw_r),
             M.sin(pitch_r),
             -M.cos(pitch_r) * M.cos(yaw_r))
        start = (eye[0] + d[0], eye[1] + d[1], eye[2] + d[2])
        b = rp3.RigidBodyBuilder3D("dynamic", translation=start,
                                   linvel=(d[0] * 9.0, d[1] * 9.0, d[2] * 9.0))
        c = rp3.ColliderBuilder3D("cuboid", hx=0.5, hy=0.5, hz=0.5,
                                  density=1.5, restitution=0.2, friction=0.6)
        balls.append(world.insert(b, c)[0])

    # ── 射线交互（删除/放置 + collider 同步 + remesh）──
    info = ""

    def mouse_ray():
        yaw_r = M.radians(yaw)
        pitch_r = M.radians(pitch)
        return (M.cos(pitch_r) * M.sin(yaw_r),
                M.sin(pitch_r),
                -M.cos(pitch_r) * M.cos(yaw_r))

    def pick_voxel():
        d = mouse_ray()
        hit = world.cast_ray(tuple(eye), d, None)
        if hit is None:
            return None
        toi = hit[1]
        px = eye[0] + d[0] * toi
        py = eye[1] + d[1] * toi
        pz = eye[2] + d[2] * toi
        # 命中点 ± ε·dir → 内侧格（删）/ 外侧格（放）——`// 1` 向负无穷
        # 取整 = floor（math 模块缺席，整除语义替代）
        inside = (int((px - d[0] * 0.05) // 1),
                  int((py - d[1] * 0.05) // 1),
                  int((pz - d[2] * 0.05) // 1))
        outside = (int((px + d[0] * 0.05) // 1),
                   int((py + d[1] * 0.05) // 1),
                   int((pz + d[2] * 0.05) // 1))
        return inside, outside, (px, py, pz)

    def remove_voxel(key):
        if vw.get_voxel(*key) is None:
            return False
        vw.remove_voxel(*key)
        bh = col_bodies.pop(key, None)
        if bh is not None:
            world.remove_body(bh)
        # 露层补挂：正下方有体素则给新暴露面补 collider（消除
        # "mesh 有块物理穿"——增量近似，仅直下方向）
        below = (key[0], key[1] - 1, key[2])
        if vw.get_voxel(*below) is not None and below not in col_bodies:
            add_collider(below)
        return True

    def place_voxel(key):
        if vw.get_voxel(*key) is not None:
            return False
        vw.set_voxel(key[0], key[1], key[2], 2)
        add_collider(key)
        return True

    dragging = False
    last_pos = None                       # 拖拽差分锚（Event 无 rel——x/y 差分自算）
    text_cache = {}

    def hud_text(s, color=(210, 214, 224)):
        key = (s, color)
        if key not in text_cache:
            text_cache[key] = cjk.render(s, True, color)
        return text_cache[key]

    def draw_hud(rt):
        pygame.gfxdraw.set_transform(rt, M.mat4_translation(-500, 308, 0))
        pygame.gfxdraw.draw_surface(rt, hud_text(
            f"[voxel_mc] 体素 mesh {tri_count} 三角 | chunk {vw.chunk_count()} | "
            f"球 {len(balls)} | WASD+QE 漫游 拖拽转向 左删 右放 F 发射 R 重置"))
        pygame.gfxdraw.set_transform(rt, M.mat4_translation(-500, 288, 0))
        pygame.gfxdraw.draw_surface(rt, hud_text(info, (255, 220, 90)))

    while True:
        for e in pygame.event.get():
            if e.type == pygame.event.QUIT:
                return
            if e.type == pygame.event.KEYDOWN:
                if e.key == pygame.key.K_ESCAPE:
                    return
                if e.key == pygame.key.K_f:
                    launch_ball()
                if e.key == pygame.key.K_r:
                    for bh in list(col_bodies.values()):
                        world.remove_body(bh)
                    col_bodies.clear()
                    vw.clear()
                    build_terrain()
                    # 表面 collider 重建（R 全量重置——放置块一并清）
                    for x in range(16):
                        for z in range(16):
                            h = height[x][z]
                            add_collider((x, h - 1, z))
                    world.step_frame(1.0 / 60.0)   # 时序契约（cast_ray 前置）
                    vox_mesh, tri_count = rebuild_voxel_mesh()
                    info = "地形已重置"
            elif e.type == pygame.event.MOUSEBUTTONDOWN:
                if e.button == 1:
                    dragging = True
                    picked = pick_voxel()
                    if picked:
                        inside, outside, p = picked
                        if remove_voxel(inside):
                            vox_mesh, tri_count = rebuild_voxel_mesh()
                            info = f"删 {inside} @({p[0]:.1f},{p[1]:.1f},{p[2]:.1f})"
                        else:
                            info = f"删 {inside} 落空（air）"
                elif e.button == 3:
                    picked = pick_voxel()
                    if picked:
                        inside, outside, p = picked
                        if place_voxel(outside):
                            vox_mesh, tri_count = rebuild_voxel_mesh()
                            info = f"放 {outside} @({p[0]:.1f},{p[1]:.1f},{p[2]:.1f})"
                        else:
                            info = f"放 {outside} 落空（已有方块）"
            elif e.type == pygame.event.MOUSEBUTTONUP:
                if e.button == 1:
                    dragging = False
            elif e.type == pygame.event.MOUSEMOTION and dragging:
                if last_pos is not None:
                    yaw += (e.x - last_pos[0]) * 0.35
                    pitch = max(-85.0, min(85.0, pitch + (e.y - last_pos[1]) * 0.35))
                last_pos = (e.x, e.y)

        # 漫游（WASD 平移 + QE 升降——get_pressed 视图，Key unhashable）
        pressed = pygame.key.get_pressed()
        yaw_r = M.radians(yaw)
        d = (M.cos(M.radians(pitch)) * M.sin(yaw_r), 0.0,
             -M.cos(M.radians(pitch)) * M.cos(yaw_r))
        right = (M.cos(yaw_r), 0.0, M.sin(yaw_r))
        speed = 0.09
        if pressed.get(pygame.key.K_w):
            eye[0] += d[0] * speed; eye[2] += d[2] * speed
        if pressed.get(pygame.key.K_s):
            eye[0] -= d[0] * speed; eye[2] -= d[2] * speed
        if pressed.get(pygame.key.K_a):
            eye[0] -= right[0] * speed; eye[2] -= right[2] * speed
        if pressed.get(pygame.key.K_d):
            eye[0] += right[0] * speed; eye[2] += right[2] * speed
        if pressed.get(pygame.key.K_q):
            eye[1] -= speed
        if pressed.get(pygame.key.K_e):
            eye[1] += speed

        # 物理 + GameCamera MVP（with_view 每帧替换——letterbox 内聚直
        # 喂 uniform，免 write_camera_mvp 的 fit 组合双乘）
        world.step_frame(1.0 / 60.0)
        cam = cam.with_view(fps_view(eye, yaw, pitch))
        ac.write_buffer(cam_buf, cam.mvp())

        with screen.render() as rt:
            rt.fill((28, 34, 46))
            with screen.raw_render(depth=True) as p:
                p.set_pipeline(vox_pipe[0])
                p.set_bind_group(0, vox_bind[0])
                p.draw_mesh(vox_mesh)
                # 球（平移 + **旋转回填**——Quaternion xyzw 直呼构造 →
                # mat4_from_quat；物理翻滚碰撞与渲染姿态严格同步）
                for bh in balls:
                    x, y, z = world.translation(bh)
                    qx, qy, qz, qw = world.rotation(bh)
                    ac.write_buffer(
                        model_buf,
                        M.mat4_translation(x, y, z)
                        @ M.mat4_from_quat(M.Quaternion(qx, qy, qz, qw)))
                    p.set_pipeline(ball_pipe)
                    p.set_bind_group(0, ball_bind)
                    p.draw_mesh(ball_mesh)
            draw_hud(rt)

        # 物理数据正确性打点（60 帧一次）：球中心/速度——静止贴面判据
        # （中心 y ≈ 下方命中面 y + 0.5，容差 ±0.05）
        if frame == 120 and not balls:
            launch_ball()   # 自动发射一颗（落地核对打点——无人交互自动触发）
        if frame % 60 == 0 and balls:
            vx, vy, vz = world.linvel(balls[0])
            spd = (vx * vx + vy * vy + vz * vz) ** 0.5
            x, y, z = world.translation(balls[0])
            if spd < 0.05:
                # 体素查询判定（cast_ray 会命中球自身 collider → toi=0，
                # 非引擎异常）：球心下方 0.6 处的支撑格有体素 → 格顶 =
                # by+1，球心应 = 格顶 + 0.5
                bx, bz = int(x // 1), int(z // 1)
                by = int((y - 0.6) // 1)
                below = vw.get_voxel(bx, by, bz)
                if below is not None:
                    expected = by + 1 + 0.5
                    ok = abs(y - expected) < 0.06
                    print(f"[voxel-mc] 落地贴面核对：球心 y={y:.2f} 支撑体素 "
                          f"{bx,by,bz} 顶面 y={by + 1}（期望球心 {expected:.1f}）→ "
                          + ("PASS 物理数据正确" if ok else "FAIL 物理数据异常"))
                    st("球静止贴面（物理数据正确）", ok)

        pygame.display.flip()
        frame += 1
        await pygame.next_frame()
