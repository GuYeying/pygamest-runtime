//! pygamest-runtime —— 游戏运行时（生产宿主）。
//!
//! 三平台统一**入口嵌入 + 散文件清单形态**（2026-11-03 定约）：
//! - **入口 main.py**：build.rs 编译期 SFXE1 加密 → `include_bytes!`
//!   嵌入本二进制（exe/so/wasm 同源）——磁盘/APK 零 main 文件、零明文
//! - 桌面/Android：`<游戏>.exe|so` + `<RES_DIR_NAME>/`——模块/资源全部
//!   哈希名 .sfx（零原名）+ `_payload.sfx` 逻辑清单 + `_manifest.sfx`
//!   物理展开表（Android AssetManager 增量展开，均为密文）
//! - Web：同构布局平铺到静态服务根（模块/资源保原名密文——fetch 按
//!   URL 寻址；wasm 无哈希链）
//!
//! 启动序列：日志 → 密钥自持 init_crypto → 资源根锚定 → 嵌入入口解出
//! → 清单读（解密）→ 其余 .py 装表（fetch→register→import 定约）→
//! main 协程驱动。模块/资源可热更（替换对应 .sfx 即生效）；main 以
//! 嵌入态为准。游戏相对路径默认落资源目录；存档等绝对路径原样。
//!
//! 锁死定约：无 CLI/REPL/脚本参数面——唯一行为 = 运行随包游戏。
//! 入口 = `app_entry!` 宏（桌面 block_on / Android android_main / wasm
//! spawn_local——三平台统一，未来 iOS/HarmonyOS 免费继承）。

use pygamest_dev::host::{Host, RunRequest};

// ── 嵌入钥（build.rs 编译期嵌入——assets.key → ASSET_KEY_HEX env）──

fn key_from_embedded() -> [u8; 32] {
    let mut key = [0u8; 32];
    if let Some(hex) = std::option_env!("ASSET_KEY_HEX") {
        for (i, b) in hex.as_bytes().chunks(2).enumerate() {
            if i >= 32 {
                break;
            }
            key[i] = u8::from_str_radix(std::str::from_utf8(b).unwrap_or("0"), 16).unwrap_or(0);
        }
    }
    key
}

fn magic_from_embedded() -> [u8; 5] {
    let mut m = *b"SFXE1";
    if let Some(s) = std::option_env!("ASSET_MAGIC") {
        let b = s.as_bytes();
        if b.len() == 5 {
            m.copy_from_slice(b);
        }
    }
    m
}

/// 入口源码（**编译期嵌入密文**——build.rs 先加密产出 OUT_DIR/main.sfx，
/// include_bytes! 嵌的就是密文：磁盘零 main 文件、二进制零明文；
/// 运行时 init_crypto 后解出。缺游戏构建 = 空占位，acquire 显式报错）
fn embedded_main() -> Result<String, String> {
    let embedded: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/main.sfx"));
    starfish_pygame::sfx::decrypt_envelope(embedded)
        .map(|b| String::from_utf8_lossy(&b).to_string())
        .map_err(|e| format!("入口脚本解密失败: {e}"))
}

// ── Host 实现（runtime 驱动消费）────────────────────────────────
// 三平台同构：清单 → main.py 源码 + 其余 .py 装表（io 层按平台异步/
// 同步自动解密；脚本经 embedded_scripts 进 import finder 表）

struct GameHost;

impl Host for GameHost {
    fn name(&self) -> &'static str {
        "runtime"
    }

    fn args(&self) -> Vec<String> {
        vec!["main".into()]
    }

    // 最小字体形态：runtime 全平台不预载 CJK（纯默认英文字体）
    fn cjk_preload(&self) -> bool {
        false
    }

    async fn acquire(&self) -> Result<RunRequest, String> {
        // 入口：编译期嵌入密文解出（非磁盘文件——main 不入清单装载链，
        // 以嵌入态为准；模块/资源走清单哈希链，可热更替换）
        let code = embedded_main()?;
        if code.trim().is_empty() {
            return Err("入口空缺（构建未含游戏——检查 pack.toml [game]/[scripts]）".into());
        }

        // 载荷清单（SFXE1 加密——io 读链自动解密）：模块 + 资源逻辑路径
        let manifest = starfish_pygame::sfx::read("_payload.sfx")
            .await
            .map_err(|e| format!("载荷清单读取失败: {e}"))?;
        let payload: Vec<String> = String::from_utf8_lossy(&manifest)
            .lines()
            .map(|l| l.trim().to_string())
            .filter(|l| !l.is_empty() && l != "main.py")
            .collect();
        starfish_debug::log_info!(format!("[runtime] 载荷清单 {} 个", payload.len()));

        // CJK 字体资产预载（egui 面板中文——egui 无内建默认字体，不带
        // assets/fonts/cjk.ttf 时 egui 文本全灭变方块）。miss 仅记日志
        // （纯英文 egui 游戏可不带）
        match starfish_pygame::sfx::read(&format!("{}/fonts/cjk.ttf", env!("RES_DIR_NAME"))).await
        {
            Ok(b) => {
                starfish_pygame::font::preload("cjk", b);
                starfish_debug::log_info!("[runtime] CJK 字体已预载（assets/fonts/cjk.ttf）");
            }
            Err(_) => {
                starfish_debug::log_info!("[runtime] CJK 字体资产未携带（egui 中文将缺字）");
            }
        }

        // 其余 .py 全量读 + 装表（游戏 `import` 即命中——查表缓存定约）。
        // 资源目录前缀下的 .py 属**热更资源**（.sfx 哈希链，游戏按需
        // fetch——不入装表，否则内嵌版会压住热更版本）
        let res_prefix = format!("{}/", env!("RES_DIR_NAME"));
        let mut entries: Vec<(String, String, String, bool)> = Vec::new();
        for path in &payload {
            if path.ends_with(".py") && path != "main.py" && !path.starts_with(&res_prefix) {
                match starfish_pygame::sfx::read(path).await {
                    Ok(src) => {
                        let name = path.trim_end_matches(".py").replace('/', ".");
                        entries.push((
                            name,
                            path.clone(),
                            String::from_utf8_lossy(&src).to_string(),
                            false,
                        ));
                    }
                    Err(e) => {
                        starfish_debug::log_error!(format!(
                            "[runtime] 脚本 {path} 读取失败: {e}"
                        ));
                    }
                }
            }
        }

        Ok(RunRequest {
            name: "main.py".into(),
            code,
            module_root: None,
            embedded_scripts: Some(entries),
            payload: Some(payload),
        })
    }
}

// ── 入口（app_entry! 三平台统一——桌面 / Android / wasm）────────

starfish_std::app_entry!({
    // ── 桌面/Android：exe|so 旁资源根（脚本+资源全散文件）──
    #[cfg(not(target_arch = "wasm32"))]
    {
        // 0) 自身二进制定位 + cwd 锚定：
        //    桌面 = current_exe；Android NativeActivity = /proc/self/maps
        //    扫描 libruntime_android.so（current_exe 在 Android 是
        //    app_process——不是我们的库，锚定必须用真身路径）
        #[cfg(target_os = "android")]
        let exe = {
            let own = (|| {
                let maps = std::fs::read_to_string("/proc/self/maps").ok()?;
                for line in maps.lines() {
                    if let Some(p) = line.split_whitespace().last() {
                        if p.ends_with("libruntime_android.so") {
                            return Some(std::path::PathBuf::from(p));
                        }
                    }
                }
                None
            })();
            own.unwrap_or_else(|| {
                starfish_debug::log_error!(
                    "[runtime] /proc/self/maps 未找到 libruntime_android.so"
                );
                std::process::exit(2);
            })
        };
        #[cfg(not(target_os = "android"))]
        let exe = std::env::current_exe().expect("current_exe");
        let exe_dir = exe.parent().map(|p| p.to_path_buf()).unwrap_or_default();
        let _ = std::env::set_current_dir(&exe_dir);

        starfish_debug::log::init(starfish_debug::log::LogConfig {
            // 发行（release）= Info：只剩壳里程碑 + 告警/错误——开发诊断已在
            // 各处归位 Debug，不落发行日志；壳自身开发构建（debug_assertions）
            // = Debug 全量（改壳时的归因仪表）
            level: if cfg!(debug_assertions) {
                starfish_debug::log::Level::Debug
            } else {
                starfish_debug::log::Level::Info
            },
            file: Some(std::path::PathBuf::from("game.log")),
            remote: None,
            console: None,
        });
        starfish_debug::log_info!("[runtime] 启动（入口嵌入 + 散文件清单形态）");

        // 基目录 = exe 同级（**镜像源项目结构**：assets/ modules/ 与
        // 二进制同级——2026-11-03 用户定约，Python 模块加载规则按基目录
        // 直达）；密钥自持（OnceLock 先到先得——同时压过共享驱动里
        // dev 库编译期 env 的接线，两树钥不同也不再意外耦合）
        starfish_io::set_base_dir(&exe_dir);
        starfish_debug::log_info!("[runtime] 基目录 = <exe>/（assets/ modules/ 同级镜像源结构）");
        starfish_pygame::sfx::init_crypto(key_from_embedded(), magic_from_embedded());

        // [Android] 资产展开（解密编排归 sfx 层）：APK assets/ 根的
        // _manifest.sfx → 解密 → 逐名裸复制到 data_dir 根（镜像源结构，
        // 增量）→ base_dir 指向 data_dir。句柄已在 starfish-we android_init
        // 时移交 io。
        #[cfg(target_os = "android")]
        starfish_pygame::sfx::android_expand_assets();

        let host = GameHost;
        starfish_std::run_control::reset();
        let exit_code = pygamest_dev::runtime::run(&host).await;
        starfish_debug::log_info!(format!("[runtime] 结束（退出码 {exit_code}）"));
    }

    // ── Web：同构布局平铺到静态服务根（fetch 承载；密钥接线无害——
    //    明文经 unwrap_envelope 原样透传）──
    #[cfg(target_arch = "wasm32")]
    {
        starfish_debug::log::init(starfish_debug::log::LogConfig {
            level: starfish_debug::log::Level::Info,
            file: None, // wasm 无文件系统——诊断直出控制台
            remote: None,
            console: Some(starfish_debug::log::Level::Info),
        });
        starfish_debug::log_info!("[runtime] 启动（Web 散文件 + 清单形态）");
        // Web 资源前缀（编译期 pack.toml [wasm] base_url 嵌入——游戏嵌
        // 网站子路径时的资源根；空 = 页面相对语义不变。统一时点定约：
        // base_dir 接线恒在 init_crypto 与 runtime::run 之前）
        if let Some(prefix) = std::option_env!("WASM_BASE_URL") {
            if !prefix.is_empty() {
                starfish_io::set_base_dir(prefix);
                starfish_debug::log_info!(format!("[runtime] Web 资源前缀 = {prefix}"));
            }
        }
        starfish_pygame::sfx::init_crypto(key_from_embedded(), magic_from_embedded());
        let host = GameHost;
        starfish_std::run_control::reset();
        let exit_code = pygamest_dev::runtime::run(&host).await;
        starfish_debug::log_info!(format!("[runtime] 结束（退出码 {exit_code}）"));
    }
});
