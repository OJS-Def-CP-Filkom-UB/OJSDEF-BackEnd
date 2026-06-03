from app.workers.diagnostics import DIAGNOSTIC_CODES, is_valid_code


def test_all_codes_present():
    expected = {
        "PLUGIN_UNREACHABLE", "PROBE_HTTP_500", "HMAC_MISMATCH",
        "CHALLENGE_MISMATCH", "TRIGGER_REJECTED", "CALLBACK_TIMEOUT",
    }
    assert set(DIAGNOSTIC_CODES) == expected


def test_is_valid_code():
    assert is_valid_code("PROBE_HTTP_500") is True
    assert is_valid_code("NOPE") is False
