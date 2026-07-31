"""Fail-closed brake shared by build, sentry, and rotation flows."""

from __future__ import annotations

HARD_STOPS = {
    "AUTHORITY_MISMATCH", "DUAL_WRITER", "MOVING_INPUT", "STALE_RECEIPT",
    "PROFILE_LOSS", "SENTINEL_REHYDRATION_FAIL", "HIDDEN_RETRY",
    "UNQUALIFIED_CARRIER", "ORACLE_CONTAMINATION", "EXTERNAL_EFFECT_UNAUTHORIZED",
}


def evaluate(signals: dict[str, bool]) -> list[str]:
    stops: list[str] = []
    for name, active in signals.items():
        if not isinstance(active, bool):
            stops.append(f"INVALID_SIGNAL_VALUE:{name}")
        elif active and name in HARD_STOPS:
            stops.append(name)
        elif active:
            stops.append(f"UNKNOWN_HARD_STOP:{name}")
    return sorted(stops)


def assert_clear(signals: dict[str, bool]) -> None:
    stops = evaluate(signals)
    if stops:
        raise RuntimeError("FAIL_CLOSED:" + ",".join(stops))
