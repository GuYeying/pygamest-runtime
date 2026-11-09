package com.starfish.runtime;

import android.app.Activity;
import android.os.Bundle;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.widget.FrameLayout;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/** 全屏 SurfaceView 宿主：APK assets 递归拷 filesDir → attach →
 *  runEmbedded（嵌入入口自动点火——零脚本参数面，锁定语义）。 */
public class MainActivity extends Activity implements SurfaceHolder.Callback {
    private static final String TAG = "RtActivity";

    private static void log(String s) {
        android.util.Log.i(TAG, s);
    }

    private TextInputSurfaceView sv;
    private int activeGen = 0;
    private int myGen = 0;
    private boolean runSent = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Java 崩溃钩子（鸿蒙卓易通无 adb logcat——Java 侧崩溃唯一取证）
        final Thread.UncaughtExceptionHandler prev =
                Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((t, e) -> {
            log("[JAVA CRASH] " + t.getName() + ": " + e);
            for (StackTraceElement s : e.getStackTrace()) log("  at " + s);
            if (prev != null) prev.uncaughtException(t, e);
        });

        RtHost.initContext(getApplicationContext());
        log("onCreate ndk-context 已绑定");

        // 全屏沉浸
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_FULLSCREEN);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xFF000000);
        sv = new TextInputSurfaceView(this, new TextInputSurfaceView.TextSink() {
            @Override public void onText(String text) { RtHost.injectText(text); }
            @Override public void onDelete() { RtHost.injectBackspace(); }
        });
        sv.getHolder().addCallback(this);
        root.addView(sv, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(root);

        copyAssetsToFiles("", getFilesDir().getAbsolutePath());
        RtHost.setBaseDir(getFilesDir().getAbsolutePath());

        // 诊断落点：优先 /sdcard/Download（用户可见、免 root 直拉）
        File logDir;
        File dl = new File("/sdcard/Download");
        try {
            dl.mkdirs();
            File probe = new File(dl, ".probe");
            FileOutputStream t = new FileOutputStream(probe);
            t.close();
            probe.delete();
            logDir = dl;
        } catch (IOException e) {
            logDir = getExternalFilesDir(null);
            if (logDir == null) logDir = getFilesDir();
        }
        RtHost.setLogDir(logDir.getAbsolutePath());
        log("onComplete logDir=" + logDir.getAbsolutePath());
    }

    /** APK assets/** → filesDir/**（结构保留——.sfx 密文原样搬运，
     *  解密归 io 哈希链；增量语义由引擎侧 hash 直达天然承载） */
    private void copyAssetsToFiles(String assetPath, String dstDir) {
        try {
            String[] names = getAssets().list(assetPath);
            if (names == null || names.length == 0) {
                copyAssetFile(assetPath, new File(dstDir));
                return;
            }
            new File(dstDir).mkdirs();
            for (String n : names) {
                copyAssetsToFiles(
                        assetPath.isEmpty() ? n : assetPath + "/" + n,
                        new File(dstDir, n).getAbsolutePath());
            }
        } catch (IOException e) {
            log("[copyAssets] " + assetPath + ": " + e);
        }
    }

    private void copyAssetFile(String assetPath, File dst) {
        InputStream in = null;
        OutputStream out = null;
        try {
            in = getAssets().open(assetPath);
            dst.getParentFile().mkdirs();
            out = new FileOutputStream(dst);
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        } catch (IOException e) {
            log("[copyAssetFile] " + assetPath + ": " + e);
        } finally {
            try { if (in != null) in.close(); } catch (IOException ignored) {}
            try { if (out != null) out.close(); } catch (IOException ignored) {}
        }
    }

    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        log("surfaceCreated → attach");
        myGen = ++activeGen;
        RtHost.attachSurface(holder.getSurface());
        if (!runSent) {
            runSent = true;
            log("runEmbedded 点火");
            RtHost.runEmbedded();
        }
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
        log("surfaceChanged " + width + "x" + height);
        RtHost.surfaceResized(width, height);
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        if (myGen != activeGen) {
            log("surfaceDestroyed 陈旧（gen " + myGen + " < " + activeGen + "）——忽略");
            return;
        }
        log("surfaceDestroyed → stop + detach");
        RtHost.stop();
        RtHost.detachSurface(holder.getSurface());
    }

    private float downX, downY;
    private long downAt;



    @Override
    public boolean onTouchEvent(MotionEvent e) {
        int a = e.getActionMasked();
        int action;
        if (a == MotionEvent.ACTION_DOWN) action = 0;
        else if (a == MotionEvent.ACTION_MOVE) action = 1;
        else if (a == MotionEvent.ACTION_UP || a == MotionEvent.ACTION_CANCEL) action = 2;
        else return false;
        if (a == MotionEvent.ACTION_DOWN) {
            downX = e.getX(); downY = e.getY();
            downAt = android.os.SystemClock.uptimeMillis();
        }
        final boolean tap = a == MotionEvent.ACTION_UP
                && android.os.SystemClock.uptimeMillis() - downAt < 250
                && Math.abs(e.getX() - downX) < 24
                && Math.abs(e.getY() - downY) < 24;
        RtHost.injectTouch(action, e.getX(), e.getY());
        // 隐式文本输入轮询（egui wants_keyboard 状态 → 软键盘自动跟；
        // egui-starfish-we 桥层驱动标志，本层只读）
        boolean wanted = RtHost.isTextInputWanted();
        if (wanted != keyboardShown) {
            if (wanted) showKeyboard();
            else hideKeyboard();
            keyboardShown = wanted;
        }
        // 点按文本输入对话框（非 egui 脚本的输入通道——原生 EditText
        // 完整 IME 能力；egui 输入框点按让位隐式链：延迟判定 dodging
        // 引擎线程异步翻转的竞速）
        if (tap) {
            new android.os.Handler(android.os.Looper.getMainLooper()).postDelayed(() -> {
                if (!RtHost.isTextInputWanted() && !keyboardShown) showTextDialog();
            }, 250);
        }
        return true;
    }

    private boolean keyboardShown = false;

    /** 呼出软键盘（served view 焦点前置——requestFocus 后 showSoftInput） */
    private void showKeyboard() {
        try {
            sv.requestFocus();
            android.view.inputmethod.InputMethodManager imm =
                    (android.view.inputmethod.InputMethodManager)
                            getSystemService(INPUT_METHOD_SERVICE);
            imm.showSoftInput(sv, android.view.inputmethod.InputMethodManager.SHOW_IMPLICIT);
            log("showKeyboard 请求已发");
            // startInput 未就绪时首调静默失败（焦点/连接竞速）——延迟补一刀
            new android.os.Handler(android.os.Looper.getMainLooper()).postDelayed(() -> {
                if (RtHost.isTextInputWanted()) {
                    imm.showSoftInput(sv,
                            android.view.inputmethod.InputMethodManager.SHOW_IMPLICIT);
                }
            }, 120);
        } catch (Exception e) {
            log("showKeyboard 失败: " + e);
        }
    }

    /** 收起软键盘（clearFocus 归还——下轮弹出干净重挂） */
    private void hideKeyboard() {
        try {
            android.view.inputmethod.InputMethodManager imm =
                    (android.view.inputmethod.InputMethodManager)
                            getSystemService(INPUT_METHOD_SERVICE);
            imm.hideSoftInputFromWindow(sv.getWindowToken(), 0);
            sv.clearFocus();
            log("hideKeyboard 请求已发");
        } catch (Exception e) {
            log("hideKeyboard 失败: " + e);
        }
    }

    /** 弹出文本输入对话框（原生 EditText——完整 IME 能力） */
    private void showTextDialog() {
        runOnUiThread(() -> {
            try {
                android.app.AlertDialog.Builder b = new android.app.AlertDialog.Builder(this);
                final android.widget.EditText et = new android.widget.EditText(this);
                et.setText("");
                b.setTitle("文本输入").setView(et)
                 .setPositiveButton("确定", (d, w) -> {
                     String text = et.getText().toString();
                     if (!text.isEmpty()) RtHost.injectText(text);
                 })
                 .setNegativeButton("取消", null)
                 .show();
            } catch (Exception e) {
                android.util.Log.e("RtActivity", "showTextDialog", e);
            }
        });
    }
}
