import os
import re
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT, "tieba_reply_stats", "version.py")
VERSION_INFO = os.path.join(ROOT, "assets", "version_info.txt")
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
GUI = os.path.join(ROOT, "tieba_gui.py")


def read_version():
    text = open(VERSION_FILE, encoding="utf-8").read()
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def test_package_exposes_version():
    import tieba_reply_stats

    assert tieba_reply_stats.__version__ == read_version()


def test_cli_version_matches():
    from tieba_reply_stats import cli

    assert cli.VERSION == read_version()


def test_gui_imports_single_source():
    text = open(GUI, encoding="utf-8").read()
    assert "from tieba_reply_stats.version import __version__ as VERSION" in text
    assert not re.search(r'^VERSION\s*=\s*"', text, re.M)


def test_version_info_matches():
    text = open(VERSION_INFO, encoding="utf-8").read()
    file_version = re.search(r"StringStruct\('FileVersion', '([^']+)'\)", text).group(1)
    product_version = re.search(r"StringStruct\('ProductVersion', '([^']+)'\)", text).group(1)
    assert file_version == read_version()
    assert product_version == read_version()


def test_pyproject_uses_dynamic_version():
    with open(PYPROJECT, "rb") as handle:
        data = tomllib.load(handle)
    assert data["project"]["dynamic"] == ["version"]
    assert data["tool"]["setuptools"]["dynamic"]["version"]["attr"] == (
        "tieba_reply_stats.version.__version__"
    )
