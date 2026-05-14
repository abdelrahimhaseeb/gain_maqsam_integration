from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

import frappe

from gain_maqsam_integration.maqsam_client import get_client as get_base_client


def normalize_whatsapp_phone(phone: str, base_client: Any | None = None) -> str:
    raw = str(phone or "").strip()
    if not raw:
        return ""

    if base_client is not None:
        normalizer = getattr(base_client, "normalize_outbound_phone", None)
        if callable(normalizer):
            normalized = str(normalizer(raw) or "").strip()
            digits = re.sub(r"\D", "", normalized)
            return f"+{digits}" if digits else ""

    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""

    if raw.startswith("+"):
        return f"+{digits}"
    if digits.startswith("00"):
        return f"+{digits[2:]}"
    if digits.startswith("05") and len(digits) == 10:
        return f"+966{digits[1:]}"
    if digits.startswith("5") and len(digits) == 9:
        return f"+966{digits}"
    return f"+{digits}"


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
            "RecipientPhone": self.normalize_whatsapp_phone(phone),
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
