package com.starfish.runtime;

import android.view.Surface;

/** pygamest-runtime JNI 门面（符号对齐 examples/runtime_android.rs）。
 *
 *  进程一次契约：一轮 runEmbedded 只跑一个程序；切换 = stop() 后重进。
 */
public final class RtHost {
    static { System.loadLibrary("runtime_android"); }

    private RtHost() {}

    private static boolean contextBound = false;
    private static android.content.Context appContext;

    /** 绑定宿主 Context（ndk-context 初始化；cpal 等 JNI 消费方依赖
     *  ——嵌入形态必调一次；包装守卫防二次初始化断言） */
    public static void initContext(android.content.Context ctx) {
        appContext = ctx;
        if (contextBound) return;
        contextBound = true;
        nativeInitContext(ctx);
    }

    private static native void nativeInitContext(android.content.Context ctx);

    /** SurfaceView.surfaceCreated → 引擎抓取 ANativeWindow */
    public static native void attachSurface(Surface surface);

    /** SurfaceView.surfaceChanged → 位图尺寸同步 */
    public static native void surfaceResized(int width, int height);

    /** SurfaceView.surfaceDestroyed → 比对清除 */
    public static native void detachSurface(Surface surface);

    /** io 基准目录（filesDir——APK assets 递归拷贝落点，哈希链直达） */
    public static native void setBaseDir(String path);

    /** 诊断落盘目录（runEmbedded 前调用一次） */
    public static native void setLogDir(String dir);

    /** 运行嵌入入口（main.py 密文嵌 .so——解密点火，引擎自起线程） */
    public static native void runEmbedded();

    /** 触摸注入：action 0=down / 1=move / 2=up（引擎自定义编码） */
    public static native void injectTouch(int action, float x, float y);

    /** IME 提交文本注入（TextInput 事件链——TextInputSurfaceView 的
     *  InputConnection.commitText 转发） */
    public static native void injectText(String text);

    /** 请求停止当前运行（帧边界收口） */
    public static native void stop();

    // ── 文本输入对话框（原生 EditText 组合方案——脚本 start_text_dialog
    //    触发，JNI 桥上叫本方法；全 UI 线程执行） ──
    private static android.widget.EditText dialogEdit;

    /** 弹出文本对话框（预填 current；确定 → textDialogResult JNI 回投）。
     *  **须在 UI 线程调用**——JNI 桥已 Handler.post 到主线程。 */
    public static void showTextDialog(String current) {
        final android.content.Context ctx = appContext;
        if (ctx == null) return;
        new android.os.Handler(android.os.Looper.getMainLooper()).post(() -> {
            try {
                android.widget.EditText et = new android.widget.EditText(ctx);
                et.setText(current);
                new android.app.AlertDialog.Builder(ctx, android.R.style.Theme_Material_Dialog)
                        .setTitle("文本输入")
                        .setView(et)
                        .setPositiveButton("确定", (d, w) -> {
                            dialogEdit = null;
                            textDialogResult(et.getText().toString());
                        })
                        .setNegativeButton("取消", (d, w) -> { dialogEdit = null; })
                        .show();
                dialogEdit = et;
            } catch (Exception e) {
                android.util.Log.e("RtHost", "showTextDialog", e);
            }
        });
    }

    private static native void textDialogResult(String text);
}
