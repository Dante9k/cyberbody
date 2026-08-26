from __future__ import annotations

import re
from dataclasses import dataclass

from .models import (
    ActionProposal,
    ComputerAction,
    RiskCategory,
    SafetyDecision,
)


@dataclass(frozen=True, slots=True)
class InspectionResult:
    purpose: str = ""
    target_label: str = ""
    risk_category: RiskCategory = RiskCategory.NONE
    decision: SafetyDecision = SafetyDecision.ALLOW
    reason: str = ""


HANDOFF_PATTERNS: dict[RiskCategory, tuple[str, ...]] = {
    RiskCategory.SAFETY_BYPASS: (
        "change password",
        "修改密码",
        "更改密码",
        "https warning",
        "证书警告",
        "paywall",
        "付费墙",
        "bypass safety",
        "绕过安全",
    ),
}

CONFIRM_PATTERNS: dict[RiskCategory, tuple[str, ...]] = {
    RiskCategory.DESTRUCTIVE: (
        "delete",
        "remove",
        "erase",
        "删除",
        "移除",
        "清空",
        "永久删除",
    ),
    RiskCategory.EXTERNAL_COMMUNICATION: (
        "send",
        "submit",
        "publish",
        "post",
        "upload",
        "发送",
        "提交",
        "发布",
        "上传",
        "unsubscribe",
        "subscribe",
        "订阅",
        "退订",
    ),
    RiskCategory.FINANCIAL: (
        "pay",
        "purchase",
        "buy now",
        "transfer",
        "checkout",
        "付款",
        "支付",
        "购买",
        "转账",
        "结算",
    ),
    RiskCategory.ACCOUNT_PERMISSION: (
        "permission",
        "access",
        "share setting",
        "api key",
        "权限",
        "访问权",
        "共享设置",
        "密钥",
    ),
    RiskCategory.INSTALL_OR_EXECUTE: (
        "install",
        "downloaded script",
        "browser extension",
        "console code",
        "安装",
        "下载的脚本",
        "浏览器扩展",
        "控制台代码",
    ),
    RiskCategory.SYSTEM_SETTING: (
        "vpn",
        "system setting",
        "security setting",
        "系统设置",
        "安全设置",
    ),
    RiskCategory.CAPTCHA: ("captcha", "验证码挑战", "人机验证"),
    RiskCategory.PROMPT_INJECTION: (
        "ignore previous instructions",
        "ignore system",
        "prompt injection",
        "忽略之前的指令",
        "忽略系统",
        "提示注入",
    ),
}

SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    re.compile(r"\b\d{6}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:password|passwd|otp|one[- ]time code)\b", re.IGNORECASE),
    re.compile(r"(?:密码|口令|一次性验证码|身份证号|银行卡号)"),
)


def _contains(text: str, patterns: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(pattern.casefold() in lowered for pattern in patterns)


class SafetyGate:
    """Deterministic final arbiter for model-proposed actions."""

    def classify(
        self,
        action: ComputerAction,
        task: str,
        inspection: InspectionResult | None = None,
    ) -> ActionProposal:
        inspected = inspection or InspectionResult()
        context = " ".join(
            part
            for part in (task, inspected.purpose, inspected.target_label, inspected.reason)
            if part
        )

        for category, patterns in HANDOFF_PATTERNS.items():
            if _contains(context, patterns):
                return self._proposal(
                    action,
                    inspected,
                    category,
                    SafetyDecision.HANDOFF,
                    "该步骤必须由用户亲自完成。",
                )

        if inspected.decision == SafetyDecision.DENY:
            return self._proposal(
                action,
                inspected,
                inspected.risk_category,
                SafetyDecision.DENY,
                inspected.reason or "安全预检拒绝了该操作。",
            )
        if inspected.decision == SafetyDecision.HANDOFF:
            return self._proposal(
                action,
                inspected,
                inspected.risk_category,
                SafetyDecision.HANDOFF,
                inspected.reason or "该步骤需要用户接管。",
            )

        if action.type == "type" and any(
            pattern.search(action.text) for pattern in SENSITIVE_PATTERNS
        ):
            return self._proposal(
                action,
                inspected,
                RiskCategory.SENSITIVE_DATA,
                SafetyDecision.CONFIRM,
                "即将输入可能的敏感数据。",
            )

        for category, patterns in CONFIRM_PATTERNS.items():
            if _contains(context, patterns):
                decision = (
                    SafetyDecision.DENY
                    if category == RiskCategory.PROMPT_INJECTION
                    else SafetyDecision.CONFIRM
                )
                return self._proposal(
                    action,
                    inspected,
                    category,
                    decision,
                    inspected.reason or "该操作可能产生外部或难以撤销的影响。",
                )

        if action.type == "keypress" and any(
            key.upper() in {"DELETE", "DEL"} for key in action.keys
        ):
            return self._proposal(
                action,
                inspected,
                RiskCategory.DESTRUCTIVE,
                SafetyDecision.CONFIRM,
                "Delete 按键可能删除数据。",
            )

        if inspected.decision == SafetyDecision.CONFIRM:
            return self._proposal(
                action,
                inspected,
                inspected.risk_category,
                SafetyDecision.CONFIRM,
                inspected.reason or "视觉预检要求确认。",
            )

        return self._proposal(
            action,
            inspected,
            inspected.risk_category,
            SafetyDecision.ALLOW,
            inspected.reason,
        )

    @staticmethod
    def _proposal(
        action: ComputerAction,
        inspected: InspectionResult,
        category: RiskCategory,
        decision: SafetyDecision,
        reason: str,
    ) -> ActionProposal:
        return ActionProposal(
            action=action,
            purpose=inspected.purpose or _default_purpose(action),
            target_label=inspected.target_label or _default_target(action),
            risk_category=category,
            decision=decision,
            reason=reason,
        )


def _default_purpose(action: ComputerAction) -> str:
    labels = {
        "click": "点击界面元素",
        "double_click": "双击界面元素",
        "move": "移动鼠标",
        "scroll": "滚动界面",
        "drag": "拖拽界面元素",
        "keypress": "发送键盘按键",
        "type": "输入文本",
        "wait": "等待界面更新",
        "screenshot": "观察当前界面",
    }
    return labels.get(action.type, action.type)


def _default_target(action: ComputerAction) -> str:
    if action.type == "type":
        return "当前输入焦点"
    if action.model_points():
        x, y = action.model_points()[0]
        return f"画面坐标 ({round(x)}, {round(y)})"
    return "当前窗口"
