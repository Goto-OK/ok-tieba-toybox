package com.tieba.stats;

import android.annotation.SuppressLint;
import android.os.Bundle;
import android.view.KeyEvent;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends android.app.Activity {

    private WebView webView;
    private int port = 0;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        PyObject server = Python.getInstance().getModule("android_server");
        try {
            port = server.callAttr("start_server", getFilesDir().getAbsolutePath()).toInt();
        } catch (Exception error) {
            android.util.Log.e("TiebaStats", "python server failed", error);
            port = 0;
        }

        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        webView.setWebViewClient(new WebViewClient());
        setContentView(webView);

        if (port > 0) {
            webView.loadUrl("http://127.0.0.1:" + port + "/");
        } else {
            webView.loadData(
                "<html><body style='font-family:sans-serif;padding:24px'>"
                + "<h3>Python 服务启动失败</h3><p>请查看 Logcat（TiebaStats）中的错误。</p>"
                + "</body></html>",
                "text/html; charset=utf-8", "UTF-8");
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView != null && webView.canGoBack()) {
            webView.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }
}
