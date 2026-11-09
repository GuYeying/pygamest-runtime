package com.starfish.runtime;

import android.content.Context;
import android.text.InputType;
import android.view.inputmethod.InputConnection;
import android.view.SurfaceView;
import android.view.inputmethod.BaseInputConnection;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;

/** 文本输入承载 SurfaceView：声明为文本编辑器（IME 可附着——软键盘
 *  呼出的前置条件），IME 提交文本经 commitText → JNI injectText
 *  （TextInput 事件链，与触摸注入同构）。
 *
 *  与 pygamest-dev 同构（2026-11-10 定案三点）：①FOCUSABLE +
 *  focusableInTouchMode（touch 模式 tap 聚焦前提——showSoftInput 要求
 *  served view 持焦）；②动态 onCheckIsTextEditor（文本输入活跃期才声明
 *  编辑器——点非输入框判非编辑器，"点哪都弹键盘"的自动链关闸）；③
 *  sendKeyEvent(KEYCODE_DEL) 拦截（退格第二路径——部分输入法删字不走
 *  deleteSurroundingText，InputConnection 层直接拦不依赖焦点分发）。
 */
class TextInputSurfaceView extends SurfaceView {
    private final TextSink sink;

    interface TextSink { void onText(String text); void onDelete(); }

    TextInputSurfaceView(Context ctx, TextSink sink) {
        super(ctx);
        this.sink = sink;
        setFocusable(FOCUSABLE);
        setFocusableInTouchMode(true);
    }

    @Override
    public boolean onCheckIsTextEditor() {
        // 动态：文本输入活跃期才声明编辑器（IMM startInput 据此挂接）
        return RtHost.isTextInputWanted();
    }

    @Override
    public InputConnection onCreateInputConnection(EditorInfo outAttrs) {
        outAttrs.inputType = InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS;
        outAttrs.imeOptions = EditorInfo.IME_FLAG_NO_FULLSCREEN
                | EditorInfo.IME_ACTION_DONE;
        return new BaseInputConnection(this, false) {
            @Override
            public boolean commitText(CharSequence text, int newCursorPosition) {
                sink.onText(text.toString());
                return true;
            }
            @Override
            public boolean deleteSurroundingText(int beforeLength, int afterLength) {
                sink.onDelete();
                return true;
            }
            @Override
            public boolean sendKeyEvent(android.view.KeyEvent event) {
                // 退格第二路径（ACTION_DOWN 消费一次防双删，其余放行默认分发）
                if (event.getAction() == android.view.KeyEvent.ACTION_DOWN
                        && event.getKeyCode() == android.view.KeyEvent.KEYCODE_DEL) {
                    sink.onDelete();
                    return true;
                }
                return super.sendKeyEvent(event);
            }
        };
    }

    @Override
    public boolean onKeyDown(int keyCode, android.view.KeyEvent event) {
        // KEYCODE_DEL = 软键盘/实体键盘的退格路径（不走 InputConnection）
        if (keyCode == android.view.KeyEvent.KEYCODE_DEL) {
            sink.onDelete();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }
}
