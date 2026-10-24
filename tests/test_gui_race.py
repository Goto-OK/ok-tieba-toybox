import tkinter as tk

import pytest

import tieba_gui
from tieba_gui import App


@pytest.fixture
def root_app():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no Tk display")
    root.withdraw()
    app = App(root)
    root.update_idletasks()
    yield root, app
    try:
        root.destroy()
    except tk.TclError:
        pass


def test_stop_closes_choice_dialog(root_app):
    root, app = root_app
    app._set_running(True)
    root.after(30, app._on_stop)
    result = app._ask_choice(
        "竞态测试",
        "停止应关闭这个选择框。",
        [("继续", "continue"), ("停止", "stop")],
    )
    root.update()
    assert result is None
    assert getattr(app, "_active_choice_window", None) is None
    assert app.stop_event.is_set()
    app._set_running(False)


def test_follow_detection_requires_login(root_app):
    _root, app = root_app
    app._set_mode("guest")
    app._refresh_webview_status()
    assert str(app.follow_enhance_check.cget("state")) == "disabled"


def test_login_cookie_enables_follow_detection(root_app):
    _root, app = root_app
    app._set_mode("login")
    app.login_method_var.set("cookie")
    app.cookie_var.set("BDUSS=test; TIEBA_SID=test")
    app._refresh_webview_status()
    assert str(app.follow_enhance_check.cget("state")) == "normal"


def test_login_result_text_for_first_time_and_existing(root_app):
    _root, app = root_app
    app.last_threads = []
    assert "开始统计" in app._login_result_text("已读取完整 Cookie")
    app.last_threads = [object()]
    assert "不会重抓" in app._login_result_text("已读取完整 Cookie")


def test_ui_mode_hides_advanced_settings(root_app, monkeypatch):
    _root, app = root_app
    monkeypatch.setattr(tieba_gui, "save_settings", lambda *_args, **_kwargs: True)
    app.ui_mode_var.set("simple")
    app.batch_concurrency_var.set("3")
    app.settings["batch_concurrency"] = 3
    app.delay_var.set("0.5")
    app._apply_ui_mode(persist=False)
    assert app.identity_row.winfo_manager() == ""
    assert app.delay_row.winfo_manager() == ""
    assert app.cache_box.winfo_manager() == ""
    assert "红绿灯并发 3" in app._hidden_advanced_settings()
    assert "请求间隔 0.5 秒" in app._hidden_advanced_settings()
    app.ui_mode_var.set("advanced")
    app._apply_ui_mode(persist=False)
    assert app.identity_row.winfo_manager() == "grid"
    assert app.delay_row.winfo_manager() == "grid"
    assert app.cache_box.winfo_manager() == "pack"


def test_login_source_conflict_is_visible(root_app, monkeypatch):
    _root, app = root_app
    app._set_mode("login")
    app.login_method_var.set("cookie")
    app.cookie_var.set("BDUSS=test; TIEBAUID=test; TIEBA_SID=test")
    app._login_source = "手动粘贴"
    monkeypatch.setattr(tieba_gui.webview2, "login_profile_exists", lambda: True)
    monkeypatch.setattr(tieba_gui.webview2, "match_profile_fingerprint", lambda _cookies: False)
    app._refresh_webview_status()
    assert "可能不是同一会话" in app.login_source_label.cget("text")


def test_login_button_text_follows_method(root_app):
    _root, app = root_app
    app._set_mode("login")
    app.login_method_var.set("bduss")
    assert "BDUSS" in app.login_baidu_btn.cget("text")
    app.login_method_var.set("cookie")
    assert "完整 Cookie" in app.login_baidu_btn.cget("text")


def test_login_baidu_uses_current_method(root_app, monkeypatch):
    _root, app = root_app
    captured = {}
    monkeypatch.setattr(tieba_gui.webview2, "available", lambda: True)
    monkeypatch.setattr(
        app,
        "_auto_get_login",
        lambda target, url="": captured.update(target=target, url=url),
    )
    app._set_mode("login")
    app.login_method_var.set("bduss")
    app._login_baidu()
    assert captured["target"] == "bduss"
    app.login_method_var.set("cookie")
    app._login_baidu()
    assert captured["target"] == "cookie"


def test_builtin_temp_login_flags_profile_conflict(root_app, monkeypatch):
    _root, app = root_app
    app._set_mode("login")
    app.login_method_var.set("cookie")
    app.cookie_var.set("BDUSS=temp; TIEBA_SID=temp")
    app._login_source = "内置浏览器"
    app._last_webview_match = False
    monkeypatch.setattr(tieba_gui.webview2, "login_profile_exists", lambda: True)
    app._refresh_webview_status()
    assert "可能不是同一会话" in app.login_source_label.cget("text")


def test_switch_login_done_replaces_profile(root_app, monkeypatch, tmp_path):
    _root, app = root_app
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    profile = tieba_gui.webview2.login_profile_dir()
    import os

    os.makedirs(profile)
    open(os.path.join(profile, "old.txt"), "w", encoding="utf-8").write("old")
    temp = tieba_gui.webview2.prepare_switch_profile()
    open(os.path.join(temp, "new.txt"), "w", encoding="utf-8").write("new")
    app.settings["webview_remember_login"] = True
    app._set_mode("login")
    app.login_method_var.set("cookie")
    monkeypatch.setattr(tieba_gui, "save_cookie", lambda _value: True)
    monkeypatch.setattr(app, "_offer_retry_incomplete", lambda *_args: None)
    app._handle_message(
        (
            "switch_login_done",
            {"BDUSS": "new", "TIEBAUID": "new-uid", "TIEBA_SID": "new-sid"},
            "",
            "",
        )
    )
    assert os.path.isfile(os.path.join(profile, "new.txt"))
    assert "BDUSS=new" in app.cookie_var.get()
    assert app._login_source == "内置浏览器"


def test_fetch_body_has_mousewheel_scroll(root_app):
    _root, app = root_app
    assert app.fetch_body.bind("<MouseWheel>")


def test_login_fields_default_collapsed(root_app):
    _root, app = root_app
    assert app._login_fields_expanded is False
    assert app.cookie_frame.winfo_manager() == ""
    assert app.bduss_frame.winfo_manager() == ""


def test_login_fields_can_collapse(root_app):
    _root, app = root_app
    app._set_login_fields_expanded(True)
    assert app.cookie_frame.winfo_manager() or app.bduss_frame.winfo_manager()
    app._set_login_fields_expanded(False)
    assert app.cookie_frame.winfo_manager() == ""
    assert app.bduss_frame.winfo_manager() == ""


def test_offline_checks_have_no_failures(root_app):
    _root, app = root_app
    results = app._offline_checks()
    assert results
    assert all(status == "PASS" for _name, status, _detail in results)


def test_simulated_cookie_action_fills_fake_login(root_app, monkeypatch):
    _root, app = root_app
    monkeypatch.setattr(app, "_ask_choice", lambda *args, **kwargs: "full_embed")
    monkeypatch.setattr(tieba_gui.messagebox, "showinfo", lambda *args, **kwargs: None)
    app._show_test_captcha_dialog("cookie")
    assert app.login_method_var.get() == "cookie"
    assert "BDUSS=TEST_BDUSS" in app.cookie_var.get()
    assert app.bduss_var.get() == "TEST_BDUSS"


def test_simulated_guest_action_keeps_guest(root_app, monkeypatch):
    _root, app = root_app
    app._set_mode("guest")
    monkeypatch.setattr(app, "_ask_choice", lambda *args, **kwargs: "guest_embed")
    monkeypatch.setattr(tieba_gui.messagebox, "showinfo", lambda *args, **kwargs: None)
    app._show_test_captcha_dialog("guest")
    assert app.mode_var.get() == "guest"
    assert app._guest_cookie.get("BAIDUID") == "TEST_GUEST"
