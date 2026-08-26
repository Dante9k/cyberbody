import json

from cyberbody.config import AppConfig, redact_secrets


def test_config_round_trip(tmp_path):
    path = tmp_path / "config.json"
    expected = AppConfig(model="gpt-5.6-terra", max_actions=25)
    expected.save(path)

    loaded = AppConfig.load(path)

    assert loaded.model == "gpt-5.6-terra"
    assert loaded.max_actions == 25


def test_invalid_config_falls_back_to_safe_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"max_actions": -1}), encoding="utf-8")

    assert AppConfig.load(path) == AppConfig()

    path.write_text("[]", encoding="utf-8")
    assert AppConfig.load(path) == AppConfig()


def test_redaction_covers_secrets_embedded_in_messages():
    value = {
        "message": "request failed for sk-example_secret_1234567890",
        "header": "Bearer abcdefghijklmnopqrstuvwxyz",
        "setting": "OPENAI_API_KEY=sk-example_secret_1234567890",
    }

    redacted = redact_secrets(value)

    assert "sk-" not in redacted["message"]
    assert redacted["header"] == "[REDACTED]"
    assert redacted["setting"] == "[REDACTED]"
