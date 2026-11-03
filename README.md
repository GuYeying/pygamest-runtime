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
cargo build --release --bin runtime     # 首次构建自动拉取 GitHub 依赖（按 Cargo.lock 锁定版本）
```

无需手动下载任何依赖仓库——跨仓依赖以 git 形式声明并锁定在 Cargo.lock。

## 三平台打包

```
python scripts/build_windows.py     # Windows/Linux：dist/<游戏>/
python scripts/build_wasm.py        # Web：dist/<游戏>-web/（静态服务即跑）
python android/build.py             # Android：target/apk/<游戏>.apk（NativeActivity 自管理）
```

配置单一源 `scripts/pack.toml`（游戏名/入口/密钥/资源目录/横竖屏）；
密钥每游戏一份（`examples/<游戏>/assets.key`，缺失自动生成，**永不入库**）。

## 生态仓库矩阵

| 仓库 | 角色 |
|---|---|
| [starfish](https://github.com/GuYeying/starfish) | 引擎本体（纯 Rust 跨平台库，零 Python 资产） |
| [pygamest](https://github.com/GuYeying/pygamest) | Python 绑定层（RustPython 内嵌 + 原生 pygame 面） |
| [pygamest-dev](https://github.com/GuYeying/pygamest-dev) | 开发解释器（python.exe 形态，零 Rust 工具链） |
| [pygamest-runtime](https://github.com/GuYeying/pygamest-runtime) | 游戏运行时（本仓，玩家单元） |
| [egui-starfish-we](https://github.com/GuYeying/egui-starfish-we) | egui × starfish-we 适配（vendored egui-winit fork） |
| [rapier-starfish-debug](https://github.com/GuYeying/rapier-starfish-debug) | Rapier 物理适配 + 通用 debug 渲染 |

## 协议

MIT OR Apache-2.0 双协议（见 LICENSE-MIT / LICENSE-APACHE）。

> 本软件按"现状"提供，不含任何形式的担保；游戏资源与分发行的使用、
> 修改与再分发遵循上述协议与资源许可。

MIT OR Apache-2.0 双协议（见 LICENSE-MIT / LICENSE-APACHE）。
