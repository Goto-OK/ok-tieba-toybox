# 参与开发

## 环境

```bash
python -m pip install -r requirements-dev.lock
python -m pip install -e . --no-deps
```

## 提交前检查

```bash
python -m ruff check .
python -m mypy
python -m pytest
python tests/selftest.py
python scripts/sync_android.py --check
```

## 约定

- 代码风格、错误处理、日志、版本、测试、Git 规则见
  [docs/standards.md](docs/standards.md)；
- 新接口先补 [docs/protocol.md](docs/protocol.md)；
- 改核心包后执行 `python scripts/sync_android.py`；
- 不要提交 Cookie、`dist/`、`.build/`、APK、Excel、快照数据。

## 提交信息

使用 `feat:` / `fix:` / `test:` / `docs:` / `chore:` 前缀，一个提交只做一件事。
