from tieba_reply_stats.profile import resolve_user


class FakeFetcher:
    def get_json(self, url, name=""):
        return {
            "data": {
                "exactMatch": {
                    "id": "2533337878",
                    "name": "u123",
                    "user_nickname": "墨如意",
                    "portrait": "tb.1.x",
                },
                "fuzzyMatch": [],
            }
        }


def test_nickname_search_accepts_dict_exact_match():
    info = resolve_user(FakeFetcher(), "墨如意", "昵称")
    assert info["uid"] == "2533337878"
    assert info["username"] == "u123"
    assert info["portrait"] == "tb.1.x"
