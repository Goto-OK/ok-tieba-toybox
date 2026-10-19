from tieba_reply_stats import bawu_deleted


class DummyFetcher:
    def __init__(self, payload):
        self.payload = payload

    def get_json(self, url):
        return self.payload


def test_parse_recover_list(monkeypatch):
    monkeypatch.setattr(bawu_deleted, "resolve_fid", lambda fetcher, fname: 1)
    payload = {
        "no": 0,
        "data": {
            "thread_list": [
                {
                    "thread_info": {"tid": 123, "title": "主题"},
                    "post_info": {
                        "pid": 456,
                        "abstract": "回复内容",
                        "user_name": "u",
                        "user_nickname": "昵称",
                    },
                    "sub_post_info": {},
                    "op_info": {"name": "吧务", "time": 1700000000},
                    "is_frs_mask": 0,
                }
            ],
            "page": {"current_page": 1, "total_page": 2},
        },
    }
    result = bawu_deleted.fetch_recovers(DummyFetcher(payload), "测试吧", uid="1")
    assert result["rows"][0]["kind"] == "回复"
    assert result["rows"][0]["content"] == "回复内容"
    assert result["rows"][0]["op_name"] == "吧务"
    assert result["total"] == 2


def test_parse_recover_info(monkeypatch):
    monkeypatch.setattr(bawu_deleted, "resolve_fid", lambda fetcher, fname: 1)
    payload = {
        "no": 0,
        "data": {
            "thread_info": {
                "title": "标题",
                "thread_id": 123,
                "post_id": 456,
                "content_detail": [{"type": 1, "text": "正文"}, {"type": 3}],
            },
            "user_info": {"user_name": "u", "user_nickname": "昵称", "id": 1},
        },
    }
    info = bawu_deleted.fetch_recover_info(DummyFetcher(payload), "测试吧", "123", "456")
    assert info["title"] == "标题"
    assert info["content"] == "正文"


def test_error_response(monkeypatch):
    monkeypatch.setattr(bawu_deleted, "resolve_fid", lambda fetcher, fname: 1)
    dummy = DummyFetcher({"no": 1, "error": "没有权限"})
    try:
        bawu_deleted.fetch_recovers(dummy, "测试吧")
    except bawu_deleted.BawuError as error:
        assert "没有权限" in str(error)
    else:
        raise AssertionError("应抛错")
