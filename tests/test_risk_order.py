from tieba_gui import App


class Mode:
    def get(self):
        return "login"


def _app():
    app = App.__new__(App)
    app.settings = {"risk_enabled": True}
    app.mode_var = Mode()
    app.blacklist = {"ban": ["坏吧"], "warn": [], "safe": []}
    return app


def test_followed_forum_alone_does_not_mark():
    app = _app()
    profile = {
        "recent_posts": [],
        "followed_forums": [{"name": "坏吧"}],
        "hidden_forums": [],
    }
    assert app._profile_hit(profile) == ("", "")


def test_post_forum_marks_after_posts_loaded():
    app = _app()
    profile = {
        "recent_posts": [{"bar": "坏吧", "title": "x"}],
        "followed_forums": [],
        "hidden_forums": [],
    }
    assert app._profile_hit(profile)[0] == "ban"
