""".env 加载器的回归护栏。

守的是**两条刻意的规则**,任何一条被无意改掉都很难查:
- pytest 下**不加载** —— 否则单测会拿到真实 key,哪天有条路径忘了打桩就真的联网了。
- **不覆盖**已存在的环境变量 —— 临时 `LLM_MODEL=... uvicorn` 必须能压过 .env。

用例全部走临时文件 + 替换 `config._ENV_FILE`,不读真实的 `backend/.env`,
所以在"本机有 key"和"CI 没有 key"两种环境下行为一致。
"""

from __future__ import annotations

import os
import sys

from app import config


def _arm(monkeypatch, tmp_path, text: str) -> None:
    """让下一次 load_local_env() 真的执行,并指向一个临时 .env(绕过 pytest 守卫)。"""
    f = tmp_path / ".env"
    if text is not None:
        f.write_text(text, encoding="utf-8")
    monkeypatch.setattr(config, "_ENV_FILE", f)
    monkeypatch.setattr(config, "_loaded", False)
    monkeypatch.delitem(sys.modules, "pytest", raising=False)


def test_pytest_never_loads_the_env_file(tmp_path, monkeypatch):
    """pytest 下 `load_local_env()` 必须是空操作 —— 不打桩就联网的最后一道闸。"""
    var = "TRIP_BALANCER_SHOULD_NOT_BE_SET"
    monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / ".env")
    (tmp_path / ".env").write_text(f"{var}=leaked\n", encoding="utf-8")
    monkeypatch.setattr(config, "_loaded", False)

    config.load_local_env()  # 注意:这里**不**摘掉 sys.modules["pytest"]

    assert var not in os.environ, "pytest 下竟然加载了 .env —— 单测可能拿真实 key 去联网"


def test_existing_environment_wins(tmp_path, monkeypatch):
    """显式传的环境变量优先于 .env(setdefault 语义)。"""
    _arm(monkeypatch, tmp_path, "LLM_MODEL=from_file\n")
    monkeypatch.setenv("LLM_MODEL", "from_shell")

    config.load_local_env()

    assert os.environ["LLM_MODEL"] == "from_shell"


def test_missing_file_is_silent(tmp_path, monkeypatch):
    """没有 .env 时静默返回 —— 新克隆下来尚未配置也能起服务。"""
    var = "TRIP_BALANCER_ABSENT_FILE"
    monkeypatch.delenv(var, raising=False)
    _arm(monkeypatch, tmp_path, None)  # 不写文件

    config.load_local_env()  # 不抛即通过

    assert var not in os.environ


def test_parses_quotes_comments_and_blank_lines(tmp_path, monkeypatch):
    var = "TRIP_BALANCER_PARSE_CHECK"
    for k in (var, "SPACED_KEY", "TRIP_BALANCER_SQ"):
        monkeypatch.delenv(k, raising=False)
    _arm(
        monkeypatch,
        tmp_path,
        "# 注释行\n"
        "\n"
        "  SPACED_KEY = spaced_val  \n"
        f'{var}="quoted value"\n'
        f"TRIP_BALANCER_SQ={var}_single\n"
        "NO_EQUALS_SIGN_LINE\n",
    )

    config.load_local_env()

    assert os.environ[var] == "quoted value"          # 双引号被剥掉
    assert os.environ["SPACED_KEY"] == "spaced_val"   # 键与值两侧空白被 strip
    assert os.environ["TRIP_BALANCER_SQ"] == f"{var}_single"  # 值里的下划线不受影响
    assert "NO_EQUALS_SIGN_LINE" not in os.environ    # 无 = 的行被跳过
    assert "  SPACED_KEY " not in os.environ          # 键也 strip 过,没有带空格的变体


def test_is_idempotent(tmp_path, monkeypatch):
    """跑第二次不该有任何变化(否则每个测试都可能重新读盘)。"""
    _arm(monkeypatch, tmp_path, "TRIP_BALANCER_IDEM=first\n")
    config.load_local_env()
    assert os.environ["TRIP_BALANCER_IDEM"] == "first"

    # 改文件内容,但已经 _loaded=True 了 —— 不该被重新读入
    (tmp_path / ".env").write_text("TRIP_BALANCER_IDEM=second\n", encoding="utf-8")
    config.load_local_env()

    assert os.environ["TRIP_BALANCER_IDEM"] == "first"
    monkeypatch.delenv("TRIP_BALANCER_IDEM", raising=False)
