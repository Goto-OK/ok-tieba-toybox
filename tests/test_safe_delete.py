import os

import pytest

from tieba_reply_stats import safe_delete


def test_remove_file_rejects_outside(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    outside = tmp_path / "keep.txt"
    outside.write_text("keep", encoding="utf-8")
    with pytest.raises(safe_delete.UnsafeDelete):
        safe_delete.remove_file(str(outside), [str(root)])
    assert outside.exists()


def test_remove_tree_only_inside(tmp_path):
    root = tmp_path / "app"
    logs = root / "logs"
    logs.mkdir(parents=True)
    (logs / "a.log").write_text("x", encoding="utf-8")
    outside = tmp_path / "keep.txt"
    outside.write_text("keep", encoding="utf-8")
    safe_delete.remove_tree(str(logs), [str(root)])
    assert not logs.exists()
    assert outside.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction")
def test_remove_tree_refuses_junction(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    link = root / "logs"
    os.system(f'cmd /c mklink /J "{link}" "{target}" >nul')
    if not link.exists():
        pytest.skip("cannot create junction")
    with pytest.raises(safe_delete.UnsafeDelete):
        safe_delete.remove_tree(str(link), [str(root)])
    assert (target / "keep.txt").exists()
