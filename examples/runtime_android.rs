//! pygamest-runtime Android cdylib（**Java 宿主 + JNI 嵌入面**——卓易通
//! 兼容形态，2026-11-08 定约）。
//!
//! 背景：NativeActivity 纯原生形态（app_entry! android 分支）在鸿蒙
//! 卓易通秒闪退（实测）——兼容层对标准 Java Activity 支持最好。本形态
//! = dev 仓 android_host 的真机实证骨架（AndroidApp 面退役、JNI 面换
//! 代码源）：
//! - Java 宿主（MainActivity 全屏 SurfaceView）→ JNI attachSurface /
//!   surfaceResized / detachSurface / injectTouch（starfish-we embedded
//!   门面，dev 同款真机实证）
//! - **代码源 = 编译期嵌入密文**（build.rs → OUT_DIR/main.sfx →
//!   init_crypto 后解出）——runEmbedded 一次点火，无脚本参数面（锁定
//!   语义不变）
//! - 资产 = APK assets/ 加密散件，Java 递归拷 filesDir（结构保留）→
//!   setBaseDir(filesDir) → io 哈希链直达（桌面 dist 同构布局）
//!
//! 诊断：starfish-debug 落 <logDir>/dev_log.txt（建议 /sdcard/Download
//! ——USB 免 root 直拉）+ 原生致命信号遗嘱 + panic 回溯直写（卓易通
//! 无 adb logcat 时的唯一取证通道）。
//!
//! 构建：cargo ndk -t arm64-v8a -o jniLibs -- build --release --example
//! runtime_android（android/build.py 编排全链）。

use pygamest_dev::platform::mobile;
use starfish_we::embedded;

// ── 嵌入钥 / 入口密文（build.rs 编译期——与 bin/runtime.rs 同源）──

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

/// 入口源码解密（密文 include_bytes! → init_crypto 后解出）
fn embedded_main() -> Result<String, String> {
    let embedded: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/main.sfx"));
    starfish_pygame::sfx::decrypt_envelope(embedded)
        .map(|b| String::from_utf8_lossy(&b).to_string())
        .map_err(|e| format!("入口脚本解密失败: {e}"))
}

// ── libandroid.so 原生符号 ──────────────────────────────────────
extern "C" {
    fn ANativeWindow_getWidth(window: *mut std::ffi::c_void) -> i32;
    fn ANativeWindow_getHeight(window: *mut std::ffi::c_void) -> i32;
}

/// 直退系统调用（绕过 atexit/C++ 静态析构窗口——期间 Java 线程撞已销
/// 毁互斥锁 → FORTIFY abort → SIGABRT 闪退，真机实证）
#[cfg(target_os = "android")]
extern "C" {
    fn _exit(code: i32) -> !;
}

// ── 原生崩溃遗嘱（信号遗嘱）：致命信号死前往 dev_log 写标记 ──
#[cfg(target_os = "android")]
static DEVLOG_FD: std::sync::atomic::AtomicI32 = std::sync::atomic::AtomicI32::new(-1);

#[cfg(target_os = "android")]
const FATAL_SIGNS: [(i32, &str); 6] = [
    (4, "SIGILL"),
    (6, "SIGABRT"),
    (7, "SIGBUS"),
    (8, "SIGFPE"),
    (11, "SIGSEGV"),
    (31, "SIGSYS"),
];

#[cfg(target_os = "android")]
extern "C" fn crash_handler(sig: i32) {
    let fd = DEVLOG_FD.load(std::sync::atomic::Ordering::SeqCst);
    if fd >= 0 {
        let name = FATAL_SIGNS
            .iter()
            .find(|(s, _)| *s == sig)
            .map(|(_, n)| *n)
            .unwrap_or("SIGNAL");
        let line = format!(
            "\n=== {name}（原生致命崩溃，非 Rust panic——引擎最后面包屑见上）===\n"
        );
        unsafe { write(fd, line.as_ptr().cast(), line.len() as isize) };
    }
    unsafe {
        signal(sig, 0);
        raise(sig);
    }
}

#[cfg(target_os = "android")]
extern "C" {
    fn signal(sig: i32, handler: usize) -> usize;
    fn write(fd: i32, buf: *const u8, count: isize) -> isize;
    fn raise(sig: i32) -> i32;
}

#[cfg(target_os = "android")]
fn install_crash_handlers(log_path: &str) {
    use std::os::unix::io::AsRawFd;
    if let Ok(f) = std::fs::OpenOptions::new()
        .append(true)
        .create(true)
        .open(log_path)
    {
        let fd = f.as_raw_fd();
        std::mem::forget(f);
        DEVLOG_FD.store(fd, std::sync::atomic::Ordering::SeqCst);
        for (sig, _) in FATAL_SIGNS {
            unsafe { signal(sig, crash_handler as usize) };
        }
    }
}

/// jstring → String（GetStringUTFChars/Release 直连；替换行为 lossy）
///
/// # Safety
/// `env`/`s` 必须为有效 JNI 句柄。
unsafe fn jstring_to_string(env: jni_sys::JNIEnv, s: jni_sys::jstring) -> String {
    let env = env as *mut jni_sys::JNIEnv;
    let get = (*(*env)).GetStringUTFChars.expect("GetStringUTFChars missing");
    let ptr = get(env, s, std::ptr::null_mut());
    let text = std::ffi::CStr::from_ptr(ptr).to_string_lossy().into_owned();
    let release = (*(*env)).ReleaseStringUTFChars.expect("ReleaseStringUTFChars missing");
    release(env, s, ptr);
    text
}

// ── 诊断基建：起点时钟 + 盖戳 + 落盘（闪退定位 = 最后一条面包屑）──
#[cfg(target_os = "android")]
static T0: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();

#[cfg(target_os = "android")]
fn stamp(s: &str) -> String {
    let ms = T0
        .get_or_init(std::time::Instant::now)
        .elapsed()
        .as_millis();
    format!("[{ms:>5}ms] {s}")
}

#[cfg(target_os = "android")]
fn write_diag(log_path: &str, line: &str) {
    use std::io::Write;
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .append(true)
        .create(true)
        .open(log_path)
    {
        let _ = writeln!(f, "{line}");
    }
}

// ── android_main 符号 satisfy（starfish-we android 后端链接期引用——
// 不定义则 dlopen 报 UnsatisfiedLinkError 实测）。JNI 形态不走
// NativeActivity 路径：空实现永不被调（manifest 启动 = MainActivity）。──
#[cfg(target_os = "android")]
#[no_mangle]
pub extern "C" fn android_main(_app: android_activity::AndroidApp) {
    starfish_debug::log_warn!("[runtime] android_main 被调（NativeActivity 误入）——Java 宿主形态请以 MainActivity 启动");
}

// ── JNI 面（com.starfish.runtime.RtHost——符号逐一对齐 Java）──────

/// 绑定宿主 Context（ndk-context 初始化——cpal/robius 等 JNI 消费方
/// 依赖；嵌入形态无 glue 无人初始化，包装层守卫防二次断言）
#[no_mangle]
pub extern "system" fn Java_com_starfish_runtime_RtHost_nativeInitContext(
    env: jni_sys::JNIEnv,
    _clazz: jni_sys::jclass,
    context: jni_sys::jobject,
) {
    unsafe {
        let env = env as *mut jni_sys::JNIEnv;
        let get_vm = (*(*env)).GetJavaVM.expect("GetJavaVM missing");
        let mut vm: *mut jni_sys::JavaVM = std::ptr::null_mut();
        if get_vm(env, &mut vm) != 0 {
            starfish_debug::log_error!("[runtime] GetJavaVM 失败——ndk-context 未绑定");
            return;
        }
        let new_ref = (*(*env)).NewGlobalRef.expect("NewGlobalRef missing");
        let gref = new_ref(env, context);
        ndk_context::initialize_android_context(vm.cast(), gref.cast());
        starfish_debug::log_info!("[runtime] ndk-context 已绑定（VM + 全局引用）");
    }
}

/// 注入诊断落盘目录（onCreate 早期调用一次——日志/panic 回溯全落此）
#[no_mangle]
pub extern "system" fn Java_com_starfish_runtime_RtHost_setLogDir(
    env: jni_sys::JNIEnv,
    _clazz: jni_sys::jclass,
    dir: jni_sys::jstring,
) {
    let dir = unsafe { jstring_to_string(env, dir) };
    let _ = T0.set(std::time::Instant::now());
    let log_path = format!("{dir}/dev_log.txt");
    let _ = std::fs::remove_file(&log_path);
    install_crash_handlers(&log_path);
    starfish_debug::log::init(starfish_debug::log::LogConfig {
        level: starfish_debug::log::Level::Info,
        file: Some(std::path::PathBuf::from(&log_path)),
        remote: None,
        console: Some(starfish_debug::log::Level::Warn),
    });
    write_diag(&log_path, &format!(
        "[setLogDir] 通道自检 ok（{}）",
        stamp("diagnostics ready")
    ));
    std::panic::set_hook(Box::new(move |info| {
        let bt = std::backtrace::Backtrace::force_capture();
        let msg = stamp(&format!("[PANIC] {info}\nbacktrace:\n{bt}"));
        write_diag(&log_path, &msg);
    }));
}

/// io 基准目录（Java 把 APK assets 递归拷到 filesDir 后传入——资产/
/// 模块哈希链、存档绝对路径的锚）
#[no_mangle]
pub extern "system" fn Java_com_starfish_runtime_RtHost_setBaseDir(
    env: jni_sys::JNIEnv,
    _clazz: jni_sys::jclass,
    path: jni_sys::jstring,
) {
    let dir = unsafe { jstring_to_string(env, path) };
    let _ = std::env::set_current_dir(&dir);
    starfish_io::set_base_dir(&dir);
    starfish_debug::log_info!(format!("[runtime] 基目录 = {dir}"));
}

/// SurfaceView.surfaceCreated → 引擎抓取 ANativeWindow
#[no_mangle]
pub extern "system" fn Java_com_starfish_runtime_RtHost_attachSurface(
    env: jni_sys::JNIEnv,
    _clazz: jni_sys::jclass,
    surface: jni_sys::jobject,
) {
    unsafe { embedded::attach_surface(env as _, surface as _) };
}

#[no_mangle]
pub extern "system" fn Java_com_starfish_runtime_RtHost_surfaceResized(
    _env: jni_sys::JNIEnv,
    _clazz: jni_sys::jclass,
    width: i32,
    height: i32,
) {
    embedded::surface_resized(width.max(0) as u32, height.max(0) as u32);
    starfish_std::screen::set_screen_size(width.max(0) as u32, height.max(0) as u32);
}

#[no_mangle]
pub extern "system" fn Java_com_starfish_runtime_RtHost_detachSurface(
    env: jni_sys::JNIEnv,
    _clazz: jni_sys::jclass,
    surface: jni_sys::jobject,
) {
    unsafe { embedded::detach_surface(env as _, surface as _) };
}

/// 触摸注入：action 0=down / 1=move / 2=up（引擎自定义编码）；坐标 =
/// SurfaceView 位图像素（JNI 原生类型逐一对齐 Java：int→i32、float→f32
/// ——f64 曾致 AArch64 读出恒 0，dev 真机实证）
#[no_mangle]
pub extern "system" fn Java_com_starfish_runtime_RtHost_injectTouch(
    _env: jni_sys::JNIEnv,
    _clazz: jni_sys::jclass,
    action: i32,
    x: f32,
    y: f32,
) {
    embedded::inject_touch(action as u8, x as f64, y as f64);
}

/// 运行嵌入入口（surfaceCreated 后 Java 调一次）：init_crypto → 资产
/// 展开（Java 已拷 filesDir——此处零工作）→ 入口解密 → 引擎自起线程
/// 驱动（不占 UI 主线程）。进程一次契约：一轮只跑一个程序。
#[no_mangle]
pub extern "system" fn Java_com_starfish_runtime_RtHost_runEmbedded(
    _env: jni_sys::JNIEnv,
    _clazz: jni_sys::jclass,
) {
    starfish_debug::log_info!("[runtime] 启动（入口嵌入 + 散文件清单形态）");
    starfish_pygame::sfx::init_crypto(key_from_embedded(), magic_from_embedded());
    let code = match embedded_main() {
        Ok(c) if !c.trim().is_empty() => c,
        Ok(_) => {
            starfish_debug::log_error!("[runtime] 入口空缺（构建未含游戏）");
            return;
        }
        Err(e) => {
            starfish_debug::log_error!(format!("[runtime] {e}"));
            return;
        }
    };
    starfish_debug::log_info!("[runtime] 入口解密 ok → 引擎线程点火");
    let base = starfish_io::base_dir().map(|p| p.to_string_lossy().into_owned());
    pygamest_dev::platform::mobile::run_embedded_on_new_thread("main.py".to_string(), code, base);
}

/// IME 提交文本注入（TextInput 事件——TextInputSurfaceView 的
/// InputConnection.commitText 转发）
#[no_mangle]
pub extern "system" fn Java_com_starfish_runtime_RtHost_injectBackspace(
    _env: jni_sys::JNIEnv,
    _clazz: jni_sys::jclass,
) {
    starfish_we::embedded::inject_backspace();
}

#[no_mangle]
pub extern "system" fn Java_com_starfish_runtime_RtHost_injectText(
    env: jni_sys::JNIEnv,
    _clazz: jni_sys::jclass,
    text: jni_sys::jstring,
) {
    let text = unsafe { jstring_to_string(env, text) };
    embedded::inject_text(text);
}

/// 文本输入活跃标志（隐式 egui wants_keyboard 状态——Java onTouchEvent
/// 轮询读；egui-starfish-we 桥层自动驱动，桌面 no-op 恒 false）
#[no_mangle]
pub extern "system" fn Java_com_starfish_runtime_RtHost_isTextInputWanted(
    _env: jni_sys::JNIEnv,
    _clazz: jni_sys::jclass,
) -> jni_sys::jboolean {
    if starfish_we::text_input_active() {
        1
    } else {
        0
    }
}

#[no_mangle]
pub extern "system" fn Java_com_starfish_runtime_RtHost_stop(
    _env: jni_sys::JNIEnv,
    _clazz: jni_sys::jclass,
) {
    starfish_std::run_control::request_stop();
}
