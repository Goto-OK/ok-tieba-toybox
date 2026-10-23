import tkinter as tk

import pytest

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
