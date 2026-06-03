"""Kode diagnosa kegagalan internal scan. Mirror di FrontEnd lib/diagnostics.ts."""

DIAGNOSTIC_CODES: tuple[str, ...] = (
    "PLUGIN_UNREACHABLE",
    "PROBE_HTTP_500",
    "HMAC_MISMATCH",
    "CHALLENGE_MISMATCH",
    "TRIGGER_REJECTED",
    "CALLBACK_TIMEOUT",
)


def is_valid_code(code: str) -> bool:
    return code in DIAGNOSTIC_CODES
