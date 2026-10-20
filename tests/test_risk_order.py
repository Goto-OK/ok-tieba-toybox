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


def test_complete_follow_list_participates():
    app = _app()
    profile = {
        "recent_posts": [],
        "follow_loaded": True,
        "followed_forums": [{"name": "坏吧"}],
        "followed_private": False,
    }
    assert app._profile_hit(profile)[0] == "ban"


def test_hidden_follow_list_does_not_mark():
    app = _app()
    profile = {
        "recent_posts": [],
        "follow_loaded": True,
        "followed_forums": [{"name": "坏吧"}],
        "followed_private": True,
    }
    assert app._profile_hit(profile) == ("", "")
