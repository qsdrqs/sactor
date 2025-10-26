from sactor.utils import sanitize_config


def test_sanitize_config_removes_sensitive_keys():
    config = {
        "API_KEY": "secret",
        "database": {
            "password": "pw",
            "host": "localhost",
        },
        "list": [
            {"tokenId": "abc123", "value": 1},
            "plain",
        ],
    }

    sanitized = sanitize_config(config)

    assert "API_KEY" not in sanitized
    assert "password" not in sanitized["database"]
    assert sanitized["database"]["host"] == "localhost"
    assert sanitized["list"][0] == {"value": 1}
    assert sanitized["list"][1] == "plain"


def test_sanitize_config_handles_non_sensitive_entries():
    config = {
        "monkey_count": 5,
        "flags": ["alpha", "beta"],
    }

    sanitized = sanitize_config(config)

    assert sanitized == config


def test_sanitize_config_redacts_when_requested():
    config = {
        "apiSecret": "top",  # lowercase substring coverage
        "nested": {"ACCESS_key": "value", "other": 42},
        "items": [
            {"refreshToken": "tok"},
            "keep",
        ],
    }

    sanitized = sanitize_config(config, redact=True)

    assert sanitized["apiSecret"] == "***REDACTED***"
    assert sanitized["nested"]["ACCESS_key"] == "***REDACTED***"
    assert sanitized["nested"]["other"] == 42
    assert sanitized["items"][0]["refreshToken"] == "***REDACTED***"
    assert sanitized["items"][1] == "keep"
