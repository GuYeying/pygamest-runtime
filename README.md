# pygamest-runtime

**pygamest 游戏运行时**（玩家单元）——把 pygamest 体系开发的游戏打包成
零思考分发的成品：双击即玩，无 CLI / 无 REPL / 无脚本参数面。

[pygamest](https://github.com/GuYeying/pygamest)（Python 绑定层）里开发，
[pygamest-dev](https://github.com/GuYeying/pygamest-dev)（开发解释器）里
调试，本仓负责**最后一公里**：三平台打包 + 运行。

## 分发形态（镜像源结构）

```
hello_word/
├── hello_word.exe        ← 入口脚本密文编译期嵌入（build.rs → include_bytes!）
├── assets/…              ← 资源：哈希名 .sfx（SFXE1 加密）
├── modules/…             ← 模块：哈希名 .sfx（import 直达，可热更替换）
└── _payload.sfx          ← 逻辑路径清单（密文；壳启动解密装表）
```

- **目录形状镜像源项目**——`from module import xxx` 语义与开发期一致；
  叶子名全部哈希化，分发物零明文零原名零 `.py`
- 入口以**嵌入态**为准（磁盘零 main 文件）；模块/资源替换对应 .sfx 即热更
- 加密实现唯一归属 [pygamest](https://github.com/GuYeying/pygamest) 的
  `starfish-pygame::sfx`（加密红线：引擎侧其余 crate 零加密语义）

## 从源码构建（使用者）

```bash
git clone https://github.com/GuYeying/pygamest-runtime
cd pygamest-runtime
cargo +nightly build --release --bin runtime     # 首次构建自动拉取 GitHub 依赖（按 Cargo.lock 锁定版本）
```

无需手动下载任何依赖仓库——跨仓依赖以 git 形式声明并锁定在 Cargo.lock。
⚠️ 默认集含 ozz（上游 `std::simd`）——**构建须 nightly 工具链**
（stable 报 `core::simd` 错属预期）。

## 能力轴（feature 控制剔除）

| feature | 默认 | 说明 |
|---|---|---|
| `gui` / `physics2d` / `physics3d` | ✅ | egui 界面 + rapier 2D/3D |
| `ozz` | ✅ | 3D 骨骼动画（nightly 依赖来源） |
| `spine` | ✅ | Spine 2D 骨骼动画 |
| `live2d` | ✅ | Live2D/Cubism |
| `stdlib-full` | ⬜ | stdlib 全量冻结（缺省 = Lib_min 裁剪版） |

```bash
cargo +nightly build --release --no-default-features --features "gui,physics2d,physics3d"   # 剔除动画库
cargo +nightly build --release --no-default-features                                         # 最小形态
```

三平台打包脚本同款参数：`--features 轴列表`（叠加）与
`--no-default-features`（全剔除后按 `--features` 精选）。

## 三平台打包

```
python scripts/build_windows.py --game anim3     # Windows/Linux：dist/<游戏>/
python scripts/build_wasm.py --game anim3        # Web：dist/<游戏>-web/（静态服务即跑）
python android/build.py --game anim3             # Android：target/apk/<游戏>.apk（Java 宿主 + JNI 嵌入面——卓易通实测通过）
```

- `--game <名>`：游戏项目 = `examples/<名>/`（main.py 入口 + modules/ +
  assets/）；`--features "spine,live2d"` 叠加轴；`--no-default-features`
  剔除默认轴（Android 另有 `--install` 构建后直装）
- ⚠️ 默认集含 ozz → 脚本内部已固定走 nightly 工具链
- 配置单一源 `scripts/pack.toml`（游戏名/入口/密钥/资源目录/横竖屏）；
  密钥每游戏一份（`examples/<游戏>/assets.key`，缺失自动生成，**永不
  入库**）
- 测试：桌面双击 exe；Web 在 `dist/<游戏>-web` 起静态服务开 index.html；
  Android `adb install -r`（崩溃取证 = `/sdcard/Download/dev_log.txt`）

## 生态仓库矩阵

| 仓库 | 角色 |
|---|---|
| [starfish](https://github.com/GuYeying/starfish) | 引擎本体（纯 Rust 跨平台库，零 Python 资产） |
| [pygamest](https://github.com/GuYeying/pygamest) | Python 绑定层（RustPython 内嵌 + 原生 pygame 面） |
| [pygamest-dev](https://github.com/GuYeying/pygamest-dev) | 开发解释器（python.exe 形态，零 Rust 工具链） |
| [pygamest-runtime](https://github.com/GuYeying/pygamest-runtime) | 游戏运行时（本仓，玩家单元） |
| [egui-starfish-we](https://github.com/GuYeying/egui-starfish-we) | egui × starfish-we 适配（vendored egui-winit fork） |
| [rapier-starfish-debug](https://github.com/GuYeying/rapier-starfish-debug) | Rapier 物理适配 + 通用 debug 渲染 |



## 第三方美术资源

示例所用素材取自 LearnOpenGL（作者 Joey de Vries，
https://learnopengl.com ，许可：Creative Commons Attribution 4.0
International —— CC BY 4.0）；部分测试素材取自
[SampleLib](https://samplelib.com/zh/)（网站原创测试文件，允许下载、
修改与使用，按现状提供不提供担保）。


## 协议

MIT OR Apache-2.0 双协议（见 LICENSE-MIT / LICENSE-APACHE）。

> 本软件按"现状"提供，不含任何形式的担保；游戏资源与分发行的使用、
> 修改与再分发遵循上述协议与资源许可。

MIT OR Apache-2.0 双协议（见 LICENSE-MIT / LICENSE-APACHE）。
