"""本地开发配置 —— 从 `backend/.env` 读环境变量。

**为什么需要这个文件**:provider 的环境变量是在**进程启动时**读进去的。于是
「配置改了但服务没重启」「重启时忘了带变量」这两件事,表现出来都是同一个症状:
token 明明换过了,请求还是 401 / 502。排查成本很高 —— 真实踩过的坑是一个 12:45
起的 uvicorn 一直拿着旧 key 在跑,而前端连的正是它;磁盘上怎么改都没用。

把配置落到一个文件里之后:**换 token = 改一行 + 重启**,不用再记住一长串变量,
也不会出现"某个终端窗口里少导出了一个变量"。

两条刻意的规则:
- **不覆盖**已存在的环境变量 —— `LLM_MODEL=deepseek-v4-pro uvicorn ...` 仍然优先,
  临时切换/压测不需要动文件。
- **pytest 下不加载** —— 否则单测会拿到真实 key,哪天有条路径忘了打桩就真的联网了。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# backend/.env(app/config.py 的上两级)
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
_loaded = False


def load_local_env() -> None:
    """把 `.env` 灌进 os.environ(幂等、不覆盖已有值)。缺失时静默返回。"""
    global _loaded
    if _loaded or "pytest" in sys.modules or not _ENV_FILE.is_file():
        return
    _loaded = True
    for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        # setdefault:显式传的环境变量优先于 .env
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
