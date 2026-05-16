from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

import frappe

from gain_maqsam_integration.maqsam_client import get_client as get_base_client


E164_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")
COUNTRY_CODE_RE = re.compile(r"^\+[1-9]\d{0,2}$")
DEFAULT_WHATSAPP_COUNTRY_CODE = "+966"
LOCAL_MOBILE_WITHOUT_TRUNK_RE = re.compile(r"^5\d{8}$")


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_default_country_code(value: Any) -> str:
    digits = _digits(value)
    if digits.startswith("00"):
        digits = digits[2:]
    if not digits:
        return ""

    candidate = f"+{digits}"
    return candidate if COUNTRY_CODE_RE.fullmatch(candidate) else ""


def get_default_whatsapp_country_code() -> str:
    try:
        value = frappe.db.get_single_value("Maqsam Settings", "default_whatsapp_country_code")
    except Exception:
        value = ""

    if value in (None, ""):
        return DEFAULT_WHATSAPP_COUNTRY_CODE

    normalized = normalize_default_country_code(value)
    if not normalized:
        frappe.throw(
            "Default WhatsApp Country Code must be a valid country calling code like +966.",
            frappe.ValidationError,
        )
    return normalized


def _strip_trunk_zero_after_country(digits: str, country_digits: str) -> str:
    trunk_prefix = f"{country_digits}0"
    if digits.startswith(trunk_prefix):
        return f"{country_digits}{digits[len(trunk_prefix):]}"
    return digits


def _valid_e164_from_digits(digits: str) -> str:
    candidate = f"+{digits}"
    return candidate if E164_PHONE_RE.fullmatch(candidate) else ""


def _normalize_value_to_whatsapp_e164(value: Any, default_country_code: str) -> str:
    raw = str(value or "").strip()
    digits = _digits(raw)
    if not digits:
        return ""

    country_code = normalize_default_country_code(default_country_code) or DEFAULT_WHATSAPP_COUNTRY_CODE
    country_digits = _digits(country_code)

    if raw.startswith("+"):
        if digits.startswith("0"):
            return _valid_e164_from_digits(f"{country_digits}{digits[1:]}")
        return _valid_e164_from_digits(_strip_trunk_zero_after_country(digits, country_digits))

    if digits.startswith("00"):
        international_digits = digits[2:]
        return _valid_e164_from_digits(_strip_trunk_zero_after_country(international_digits, country_digits))

    if digits.startswith(country_digits):
        return _valid_e164_from_digits(_strip_trunk_zero_after_country(digits, country_digits))

    if digits.startswith("0") and len(digits) > 1:
        return _valid_e164_from_digits(f"{country_digits}{digits[1:]}")

    if LOCAL_MOBILE_WITHOUT_TRUNK_RE.fullmatch(digits):
        return _valid_e164_from_digits(f"{country_digits}{digits}")

    return ""


def normalize_whatsapp_phone(
    phone: str,
    base_client: Any | None = None,
    default_country_code: str | None = None,
) -> str:
    raw = str(phone or "").strip()
    if not raw:
        return ""

    if default_country_code:
        country_code = normalize_default_country_code(default_country_code)
        if not country_code:
            frappe.throw(
                "Default WhatsApp Country Code must be a valid country calling code like +966.",
                frappe.ValidationError,
            )
    else:
        country_code = get_default_whatsapp_country_code()

    candidates: list[Any] = [raw]
    if base_client is not None:
        normalizer = getattr(base_client, "normalize_outbound_phone", None)
        if callable(normalizer):
            normalized = str(normalizer(raw) or "").strip()
            if normalized:
                candidates.append(normalized)

    for candidate in candidates:
        normalized = _normalize_value_to_whatsapp_e164(candidate, country_code)
        if normalized:
            return normalized

    return ""


def validate_whatsapp_phone(
    phone: str,
    base_client: Any | None = None,
    default_country_code: str | None = None,
) -> str:
    normalized = normalize_whatsapp_phone(
        phone,
        base_client=base_client,
        default_country_code=default_country_code,
    )
    if not normalized:
        frappe.throw(
            "WhatsApp recipient phone must be a valid E.164 number. "
            "Local numbers are normalized with the Default WhatsApp Country Code setting.",
            frappe.ValidationError,
        )
    return normalized


class MaqsamWhatsAppClient:
    def __init__(self, base_client: Any | None = None) -> None:
        self.base_client = base_client or get_base_client()

    def _request(self, method: str, path: str, **kwargs) -> Any:
        request = getattr(self.base_client, "_request", None)
        if not callable(request):
            frappe.throw("Configured Maqsam client does not expose a reusable request helper.")
        return request(method, path, **kwargs)

    def normalize_phone(self, phone: str) -> str:
        normalizer = getattr(self.base_client, "normalize_outbound_phone", None)
        if callable(normalizer):
            return normalizer(phone)
        return str(phone or "").strip()

    def normalize_whatsapp_phone(self, phone: str) -> str:
        return normalize_whatsapp_phone(phone, base_client=self.base_client)

    def list_templates(self) -> Any:
        return self._request("GET", "/v2/whatsapp/templates")

    def _build_send_payload(
        self,
        *,
        phone: str,
        template_id: str,
        variables: dict[str, Any] | list[Any] | str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "RecipientPhone": validate_whatsapp_phone(phone, base_client=self.base_client),
            "TemplateId": template_id,
        }
        if variables not in (None, {}, []):
            payload["TemplateVariables"] = json.dumps(variables, ensure_ascii=True, sort_keys=True) if isinstance(variables, (dict, list)) else variables
        return payload

    def send_template_message(
        self,
        *,
        phone: str,
        template_id: str,
        variables: dict[str, Any] | list[Any] | str | None = None,
        language: str | None = None,
        conversation_id: str | None = None,
    ) -> Any:
        payload = self._build_send_payload(phone=phone, template_id=template_id, variables=variables)
        return self._request("POST", "/v2/whatsapp/messages/send_message", form_payload=payload)

    def get_conversation(self, conversation_id: str) -> Any:
        if not conversation_id:
            frappe.throw("Conversation ID is required.")
        return self._request("GET", f"/v2/whatsapp/conversations/{quote(str(conversation_id).strip())}")


def get_client() -> MaqsamWhatsAppClient:
    cached = getattr(frappe.local, "_maqsam_whatsapp_client", None)
    if cached is not None:
        return cached

    client = MaqsamWhatsAppClient()
    try:
        frappe.local._maqsam_whatsapp_client = client
    except Exception:
        pass
    return client
