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

    /** 绑定宿主 Context（ndk-context 初始化；cpal 等 JNI 消费方依赖
     *  ——嵌入形态必调一次；包装守卫防二次初始化断言） */
    public static void initContext(android.content.Context ctx) {
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

    /** 诊断落盘目录（runEmbedded 前调用一次）：嵌入形态无 glue，stdout
     *  无 logcat 重定向——引擎诊断同步落 <dir>/dev_log.txt。建议传
     *  /sdcard/Download（用户可见）或 getExternalFilesDir(null) */
    public static native void setLogDir(String dir);

    /** 运行嵌入入口（main.py 密文嵌 .so——解密点火，引擎自起线程） */
    public static native void runEmbedded();

    /** 触摸注入：action 0=down / 1=move / 2=up（引擎自定义编码） */
    public static native void injectTouch(int action, float x, float y);

    /** 请求停止当前运行（帧边界收口） */
    public static native void stop();
}
