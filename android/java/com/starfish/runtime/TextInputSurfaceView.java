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
 *  （TextInput 事件链，与触摸注入同构）。 */
class TextInputSurfaceView extends SurfaceView {
    private final TextSink sink;

    interface TextSink { void onText(String text); }

    TextInputSurfaceView(Context ctx, TextSink sink) {
        super(ctx);
        this.sink = sink;
    }

    @Override
    public boolean onCheckIsTextEditor() { return true; }

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
                RtHost.injectBackspace();
                return true;
            }
        };
    }
}
