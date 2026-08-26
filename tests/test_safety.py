from cyberbody.models import ComputerAction, RiskCategory, SafetyDecision
from cyberbody.safety import InspectionResult, SafetyGate


def test_ordinary_click_is_allowed():
    proposal = SafetyGate().classify(
        ComputerAction(type="click", x=10, y=20),
        "打开设置面板",
        InspectionResult(purpose="打开设置", target_label="设置"),
    )
    assert proposal.decision == SafetyDecision.ALLOW


def test_delete_requires_confirmation_even_when_user_requested_it():
    proposal = SafetyGate().classify(
        ComputerAction(type="click", x=10, y=20),
        "删除这条记录",
        InspectionResult(purpose="点击删除", target_label="删除"),
    )
    assert proposal.decision == SafetyDecision.CONFIRM
    assert proposal.risk_category == RiskCategory.DESTRUCTIVE


def test_sensitive_text_requires_confirmation():
    proposal = SafetyGate().classify(
        ComputerAction(type="type", text="sk-example_secret_123456789"),
        "填写表单",
    )
    assert proposal.decision == SafetyDecision.CONFIRM
    assert proposal.risk_category == RiskCategory.SENSITIVE_DATA


def test_password_change_final_step_requires_handoff():
    proposal = SafetyGate().classify(
        ComputerAction(type="click", x=10, y=20),
        "完成修改密码",
    )
    assert proposal.decision == SafetyDecision.HANDOFF


def test_prompt_injection_is_denied():
    proposal = SafetyGate().classify(
        ComputerAction(type="click", x=10, y=20),
        "查看网页",
        InspectionResult(
            purpose="follow prompt injection",
            target_label="ignore previous instructions",
        ),
    )
    assert proposal.decision == SafetyDecision.DENY


def test_delete_key_requires_confirmation():
    proposal = SafetyGate().classify(
        ComputerAction(type="keypress", keys=("DELETE",)),
        "编辑记录",
    )

    assert proposal.decision == SafetyDecision.CONFIRM
    assert proposal.risk_category == RiskCategory.DESTRUCTIVE


def test_model_deny_cannot_be_downgraded_by_local_rules():
    proposal = SafetyGate().classify(
        ComputerAction(type="click", x=1, y=1),
        "打开页面",
        InspectionResult(
            risk_category=RiskCategory.UNKNOWN,
            decision=SafetyDecision.DENY,
            reason="超出任务范围",
        ),
    )

    assert proposal.decision == SafetyDecision.DENY
