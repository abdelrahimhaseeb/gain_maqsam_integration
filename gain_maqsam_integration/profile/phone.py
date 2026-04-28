from __future__ import annotations

import re
from typing import Any


def digits_only(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def phone_suffix(phone: str) -> str:
    digits = digits_only(phone)
    return digits[-7:] if len(digits) >= 7 else digits


def phone_matches(left: Any, right: Any) -> bool:
    left_digits = digits_only(left)
    right_digits = digits_only(right)
    if not left_digits or not right_digits:
        return False

    if left_digits == right_digits:
        return True

    suffix_length = min(9, len(left_digits), len(right_digits))
    return suffix_length >= 7 and left_digits[-suffix_length:] == right_digits[-suffix_length:]


def phone_matches_any(value: Any, candidates: list[Any]) -> bool:
    return any(phone_matches(value, candidate) for candidate in candidates)
