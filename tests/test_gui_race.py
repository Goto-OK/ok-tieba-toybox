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
