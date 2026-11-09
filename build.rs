//! 构建脚本：资源加密密钥 + 资源目录名编译期嵌入 + Windows 栈 Reserve。
//!
//! `assets.key`（bundle.py 侧密钥，源码树根）存在时 → 编译期嵌入
//! （`ASSET_KEY_HEX` env → 消费于 src/bin/runtime.rs）。分发物零密钥文件。
//! `scripts/pack.toml` 的 `[resources] dir` 末段目录名 → `RES_DIR_NAME`
//! （消费于 runtime 壳 `set_base_dir`——游戏相对路径默认落该资源目录；
//! 目录名不统一，随项目配置走，缺省 `assets`）。

fn main() {
    let os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let env = std::env::var("CARGO_CFG_TARGET_ENV").unwrap_or_default();
    if os == "windows" && env == "msvc" {
        println!("cargo:rustc-link-arg-bins=/STACK:16777216");
    }
    let key_file = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("assets.key");
    if key_file.is_file() {
        println!(
            "cargo:rustc-env=ASSET_KEY_HEX={}",
            std::fs::read_to_string(&key_file).unwrap_or_default().trim()
        );
        println!("cargo:rustc-env=ASSET_MAGIC=SFXE1");
        println!("cargo:rerun-if-changed=assets.key");
    }

    // 资源目录名（pack.toml 单一配置源）
    println!("cargo:rerun-if-changed=scripts/pack.toml");
    let res_dir = pack_toml_field("resources", "dir").unwrap_or_else(|| "assets".to_string());
    println!("cargo:rustc-env=RES_DIR_NAME={}", res_dir.rsplit(['/', '\\']).next().unwrap_or("assets"));
    // Web 资源前缀（pack.toml [wasm] base_url——wasm 导出嵌网站子路径时
    // 的资源根 URL；空 = 页面相对语义不变）。消费于 runtime 壳 wasm 分支
    // set_base_dir——游戏资产与 wasm 在网站上的放置位置打包时一次声明。
    let base_url = pack_toml_field("wasm", "base_url").unwrap_or_default();
    println!("cargo:rustc-env=WASM_BASE_URL={}", base_url);

    // 密钥：pack.toml [build] key_file 相对 [scripts] root（游戏项目根——
    // 每游戏一份）；未命中时回退 crate 根 assets.key（旧布局兼容）
    let key_path = match (pack_toml_field("scripts", "root"), pack_toml_field("build", "key_file")) {
        (Some(root), Some(kf)) => {
            let p = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(root).join(&kf);
            if p.is_file() {
                p
            } else {
                std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("assets.key")
            }
        }
        _ => std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("assets.key"),
    };
    if key_path.is_file() {
        println!(
            "cargo:rustc-env=ASSET_KEY_HEX={}",
            std::fs::read_to_string(&key_path).unwrap_or_default().trim()
        );
        println!("cargo:rustc-env=ASSET_MAGIC=SFXE1");
        println!("cargo:rerun-if-changed={}", key_path.display());
    }

    // ── 入口脚本编译期加密（main → SFXE1 密文 → include_bytes! 嵌入）──
    // 用户定约（2026-11-03）：磁盘零 main 文件、二进制零明文——密文在
    // **编译前**生成（build.rs 先于编译），include 嵌的就是密文；运行时
    // 经 starfish_io::decrypt_envelope 解出。缺游戏/缺钥 = 空占位（壳
    // acquire 报"入口空缺"，裸 cargo build 不炸）。
    let out_dir = std::env::var("OUT_DIR").unwrap_or_default();
    let root = pack_toml_field("scripts", "root")
        .unwrap_or_else(|| "examples/hello_word".to_string());
    let entry = pack_toml_field("game", "entry").unwrap_or_else(|| "main".to_string());
    let magic = pack_toml_field("build", "magic").unwrap_or_else(|| "SFXE1".to_string());
    let entry_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(&root)
        .join(format!("{entry}.py"));
    if let (Some(out), Ok(src)) = (
        if out_dir.is_empty() { None } else { Some(std::path::PathBuf::from(&out_dir)) },
        std::fs::read(&entry_path),
    ) {
        let key_hex = std::fs::read_to_string(&key_path).unwrap_or_default().trim().to_string();
        if key_hex.len() == 64 {
            if let Ok(key) = hex_to_32(&key_hex) {
                use chacha20poly1305::{
                    aead::{Aead, KeyInit, Payload},
                    ChaCha20Poly1305, Key, Nonce,
                };
                // nonce = 构建时刻纳秒散列（每次构建唯一——重放窗为零）
                let nanos = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|d| d.as_nanos())
                    .unwrap_or(0);
                let mut nonce = [0u8; 12];
                for (i, b) in nonce.iter_mut().enumerate() {
                    *b = ((nanos >> (i * 8)) & 0xff) as u8;
                }
                let aead = ChaCha20Poly1305::new(Key::from_slice(&key));
                let ct = aead
                    .encrypt(
                        Nonce::from_slice(&nonce),
                        Payload {
                            msg: &src,
                            aad: b"starfish-asset-v1",
                        },
                    )
                    .expect("build.rs: entry 加密失败");
                let mut envelope = magic.as_bytes().to_vec();
                envelope.extend_from_slice(&nonce);
                envelope.extend_from_slice(&ct);
                let _ = std::fs::write(out.join("main.sfx"), &envelope);
                println!("cargo:rerun-if-changed={}", entry_path.display());
                println!("cargo:rustc-env=EMBEDDED_ENTRY_LEN={}", envelope.len());
            }
        }
    }
    // 兜底：缺游戏/缺钥也必须产出占位（include_bytes! 恒可编译；空文件
    // 经 decrypt_envelope 透传 = 空 main，壳 acquire 显式报"入口空缺"）
    if let Ok(out) = std::env::var("OUT_DIR") {
        let p = std::path::Path::new(&out).join("main.sfx");
        if !p.is_file() {
            let _ = std::fs::write(&p, b"");
        }
    }
}

fn hex_to_32(hex: &str) -> Result<[u8; 32], ()> {
    let mut out = [0u8; 32];
    for (i, b) in hex.as_bytes().chunks(2).enumerate() {
        if i >= 32 {
            return Err(());
        }
        let s = std::str::from_utf8(b).map_err(|_| ())?;
        out[i] = u8::from_str_radix(s, 16).map_err(|_| ())?;
    }
    Ok(out)
}

/// pack.toml 手解析（子集：`[节]` + `KEY = "VAL"`）——取 `[节]` 下 key 的原值
fn pack_toml_field(section: &str, key: &str) -> Option<String> {
    let text = std::fs::read_to_string(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/pack.toml"),
    )
    .ok()?;
    let mut in_sec = false;
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if line.starts_with('[') {
            in_sec = line == format!("[{section}]");
            continue;
        }
        if in_sec {
            if let Some((k, v)) = line.split_once('=') {
                if k.trim() == key {
                    return Some(v.trim().trim_matches('"').trim_matches('\'').to_string());
                }
            }
        }
    }
    None
}
