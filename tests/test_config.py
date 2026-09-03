import json

from cyberbody.config import AppConfig, _keyring_service, redact_secrets


def test_config_round_trip(tmp_path):
    path = tmp_path / "config.json"
    expected = AppConfig(
        vision_model="gpt-5.6",
        action_model="gpt-5.6-terra",
        action_base_url="https://api.example.com/v1",
        max_actions=25,
    )
    expected.save(path)

    loaded = AppConfig.load(path)

    assert loaded.vision_model == "gpt-5.6"
    assert loaded.action_model == "gpt-5.6-terra"
    assert loaded.action_base_url == "https://api.example.com/v1"
    assert loaded.max_actions == 25


def test_legacy_single_model_config_migrates_to_both_roles(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"model": "legacy-model"}), encoding="utf-8")

    loaded = AppConfig.load(path)

    assert loaded.vision_model == "legacy-model"
    assert loaded.action_model == "legacy-model"


def test_remote_base_url_requires_https(tmp_path):
    config = AppConfig(action_base_url="http://example.com/v1")

    try:
        config.save(tmp_path / "config.json")
    except ValueError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("insecure remote URL was accepted")

    AppConfig(action_base_url="http://127.0.0.1:11434/v1").save(tmp_path / "local.json")


def test_credentials_are_scoped_to_role_and_endpoint_without_exposing_url():
    vision_a = _keyring_service("vision", "https://provider-a.example/v1")
    vision_b = _keyring_service("vision", "https://provider-b.example/v1")
    action_a = _keyring_service("action", "https://provider-a.example/v1")

    assert len({vision_a, vision_b, action_a}) == 3
    assert "provider-a.example" not in vision_a


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
