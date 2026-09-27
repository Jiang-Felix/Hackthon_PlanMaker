"""AI 提供方抽象 —— 解析自然语言偏好、生成取舍解释、编排行程、自评软偏好。

- MockProvider:规则解析(关键词+标签/名称匹配),模板解释。**不具备排程能力**。
- DeepSeekProvider:调用任意 OpenAI 兼容端点(官方端点 / 自建或高校网关均可)。

⚠️ 不做静默回退:模型不可用即抛 ProviderError,绝不用 mock 糊一份看起来完整的行程。
环境变量 LLM_PROVIDER=mock|deepseek|llm|openai 切换。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from ..errors import ProviderError
from ..models import POI, DayStop, RecoSettings, StructuredPref, TagPref


class LLMProvider(ABC):
    """偏好解析、行程编排与解释的统一接口。所有 AI 接线集中在这里。"""

    name = "base"

    @abstractmethod
    def parse_text(self, text: str, pois: list[POI]) -> StructuredPref:
        """把自然语言偏好解析成结构化分级(尽可能匹配到本城市 POI)。"""

    @abstractmethod
    def explain(self, trace: dict) -> str:
        """根据决策 trace 生成一句自然语言解释。"""

    def draft_itinerary(self, trip, pois: dict[str, POI], context: str) -> str:
        """AI-harness 编排入口:生成逐日草案(JSON 字符串)。

        {"days":[{"day":0,"stops":["poi_id", ...]}]}
        trip/pois 供规则型实现使用;context(统一格式化文本)供大模型实现使用。
        默认返回空,由子类覆盖。
        """
        return "{}"

    def revise_itinerary(self, draft: str, issues: str, context: str = "") -> str:
        """收到守门失败清单后,产出修正版草案。默认原样返回。

        context 是原始请求上下文 —— 修正时必须提供,否则模型不知道合法 id 清单,
        会把「未知地点」之类的错误反复重犯。
        """
        return draft

    def parse_soft_prefs(self, text: str, vocab: list) -> "TagPref":
        """把自然语言里的模糊软偏好(体力/天气/作息/消费…)解析为词表标签分级。

        只能返回 vocab 里的 tag id;默认实现返回空(表示没听懂/无软偏好)。
        """
        return TagPref()

    def parse_reco_settings(self, text: str) -> "RecoSettings":
        """把自然语言里的全局推荐诉求(冲突策略/日程对齐/关联优先级/留白)解析为设置。"""
        return RecoSettings()

    def assess_soft(
        self,
        trip,
        stops_by_day: dict[int, list[DayStop]],
        vocab: list,
    ) -> dict:
        """对**已定稿的行程**自评每位成员的软偏好达成度。

        返回 `{participant_id: {"satisfied": [tag_id], "missed": [tag_id], "violated": [tag_id]}}`。
        默认返回空(表示未评估)—— 调用方必须把"未评估"与"未满足"区分开。

        为什么是**定稿后**单独一次调用,而不是并进 draft_itinerary:
        - 草案还在修订循环里,评估的是临时产物;定稿后评估的是真行程。
        - 与决策解耦:软偏好自评**不注入** build_context,模型无法自评自刷分。
        - 失败可隔离:自评挂了不影响已经合法的行程(仅 soft_rate 落 None)。
        """
        return {}

    def hydrate(self, text: str, pois: list[POI]) -> StructuredPref:
        """兜底入口:解析 + 过滤出本城市存在的 id。"""
        pref = self.parse_text(text, pois)
        ids = {p.id for p in pois}
        return StructuredPref(
            refuse=[x for x in pref.refuse if x in ids],
            must=[x for x in pref.must if x in ids],
            want=[x for x in pref.want if x in ids],
            ok=[x for x in pref.ok if x in ids],
        )


_PROVIDER: LLMProvider | None = None


def get_provider() -> LLMProvider:
    """按环境变量取提供方(进程内缓存单例,**不做静默回退**)。

    缓存的原因:DeepSeekProvider 持有一个 httpx.Client;每次请求都重建会泄漏连接。
    实现类在此**惰性导入**,避免 provider ↔ {mock,deepseek}_provider 循环导入。
    """
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER

    # 唯一读 env 的地方,所以 .env 也只在这里加载 —— 保证任何取 provider 的路径
    # 都已经把 backend/.env 灌进来了(pytest 下会自动跳过,见 config.load_local_env)。
    from ..config import load_local_env

    load_local_env()

    kind = os.getenv("LLM_PROVIDER", "mock").lower()
    if kind in ("deepseek", "llm", "openai"):  # 真实模型(任意 OpenAI 兼容端点)
        from .deepseek_provider import DeepSeekProvider

        try:
            _PROVIDER = DeepSeekProvider()
        except Exception as e:  # 缺 key / 初始化失败
            # 这条会成为 /api/health 的 reason(前端横幅直接展示)—— 用面向用户的措辞,
            # 不暴露环境变量名;原始异常仍由 from e 保留在服务端日志里。
            raise ProviderError(
                "AI 服务暂时不可用 —— 请稍后重试,或联系管理员检查 AI 配置"
            ) from e
    else:
        from .mock_provider import MockProvider

        _PROVIDER = MockProvider()
    return _PROVIDER


def reset_provider() -> None:
    """清空缓存(测试或切换环境变量后使用)。"""
    global _PROVIDER
    _PROVIDER = None