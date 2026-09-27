"""统一错误类型 —— 移除白盒兜底后,失败必须显式暴露而不是静默降级。"""

from __future__ import annotations


class ProviderError(RuntimeError):
    """AI 提供方不可用(未配置 key / 网络失败 / mock 不支持排程)。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PlanValidationError(RuntimeError):
    """AI 草案在 ≤2 轮修复后仍不满足硬约束(时空/预算/refuse/必去覆盖)。"""

    def __init__(self, message: str, issues: list[str] | None = None, attempts: int = 0):
        super().__init__(message)
        self.message = message
        self.issues = issues or []
        self.attempts = attempts