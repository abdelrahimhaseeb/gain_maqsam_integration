from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import frappe
import requests
from frappe.utils import cint


SETTINGS_FIELD_MAP = {
    "MAQSAM_BASE_URL": ("base_url", False),
    "MAQSAM_ACCESS_KEY_ID": ("access_key_id", False),
    "MAQSAM_ACCESS_SECRET": ("access_secret", True),
    "MAQSAM_DEFAULT_CALLER": ("default_caller", False),
    "MAQSAM_DEFAULT_AGENT_EMAIL": ("default_agent_email", False),
    "MAQSAM_TIMEOUT_SECONDS": ("timeout_seconds", False),
}

KNOWN_OFFLINE_AGENT_STATES = {"absent", "away", "disconnected", "logged_out", "offline"}


class MaqsamClient:
    def __init__(self) -> None:
        self.base_url = self._normalize_host(self._get_config_value("MAQSAM_BASE_URL"))
        self.access_key_id = self._get_config_value("MAQSAM_ACCESS_KEY_ID")
        self.access_secret = self._get_config_value("MAQSAM_ACCESS_SECRET")
        self.default_caller = self._get_optional_config_value("MAQSAM_DEFAULT_CALLER")
        self.default_agent_email = self._get_optional_config_value("MAQSAM_DEFAULT_AGENT_EMAIL")
        self.timeout = float(self._get_optional_config_value("MAQSAM_TIMEOUT_SECONDS") or 30)

        self.api_base = f"https://api.{self.base_url}"
        self.session = requests.Session()
        self.session.auth = (self.access_key_id, self.access_secret)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "gain-maqsam-integration/0.0.1",
            }
        )

    def _get_settings_doc(self):
        if not frappe.db.exists("DocType", "Maqsam Settings"):
            return None

        try:
            return frappe.get_single("Maqsam Settings")
        except Exception:
            return None

    def _get_config_value(self, key: str) -> str:
        value = self._get_optional_config_value(key)
        if value:
            return str(value).strip()

        fieldname, _is_password = SETTINGS_FIELD_MAP.get(key, (key, False))
        frappe.throw(f"Missing required Maqsam setting: {fieldname}")

    def _get_optional_config_value(self, key: str) -> str | None:
        fieldname, is_password = SETTINGS_FIELD_MAP.get(key, (None, False))

        if fieldname:
            settings = self._get_settings_doc()
            if settings:
                value = settings.get_password(fieldname) if is_password else settings.get(fieldname)
                if value not in (None, ""):
                    return str(value).strip()

        return None

    def _normalize_host(self, value: str) -> str:
        parsed = urlparse(value if "://" in value else f"https://{value}")
        host = (parsed.netloc or parsed.path).strip().strip("/")

        for prefix in ("api.", "portal."):
            if host.startswith(prefix):
                host = host[len(prefix) :]

        return host

    def _prepare_values(self, values: dict[str, Any] | None) -> dict[str, Any]:
        prepared: dict[str, Any] = {}
        for key, value in (values or {}).items():
            if value is None:
                continue
            if isinstance(value, bool):
                prepared[key] = str(value).lower()
            else:
                prepared[key] = value
        return prepared

    def _phone_key(self, value: str) -> str:
        return re.sub(r"[^\d+]", "", value)

    def _digits_only(self, value: str | None) -> str:
        return re.sub(r"\D", "", str(value or ""))

    def _infer_country_prefix(self, local_digits: str, caller: str | None = None) -> str | None:
        caller_sample = self._digits_only(caller or self.default_caller)
        if not caller_sample or not local_digits:
            return None

        prefix_length = len(caller_sample) - len(local_digits)
        if 1 <= prefix_length <= 4:
            return caller_sample[:prefix_length]

        return None

    def normalize_outbound_phone(self, phone: str, caller: str | None = None) -> str:
        raw = str(phone or "").strip()
        if not raw:
            return ""

        digits = self._digits_only(raw)
        if not digits:
            return ""

        if raw.startswith("+"):
            return digits

        if digits.startswith("00"):
            return digits[2:]

        if digits.startswith("0"):
            local_digits = digits[1:]
            country_prefix = self._infer_country_prefix(local_digits, caller=caller)
            if country_prefix:
                return f"{country_prefix}{local_digits}"

        if 6 <= len(digits) <= 15 and not digits.startswith("0"):
            country_prefix = self._infer_country_prefix(digits, caller=caller)
            if country_prefix:
                return f"{country_prefix}{digits}"

        return digits

    def _append_unique_number(self, numbers: list[str], seen: set[str], value: Any) -> None:
        if value in (None, ""):
            return

        cleaned = str(value).strip()
        if not cleaned:
            return

        key = self._phone_key(cleaned) or cleaned
        if key in seen:
            return

        seen.add(key)
        numbers.append(cleaned)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
        form_payload: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = self.session.request(
                method=method,
                url=f"{self.api_base}/{path.lstrip('/')}",
                params=self._prepare_values(params) or None,
                json=json_payload or None,
                data=self._prepare_values(form_payload) or None,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            frappe.throw(f"Maqsam connection failed: {exc}")

        if not response.ok:
            request_id = response.headers.get("X-Request-Id")
            try:
                payload = response.json()
            except ValueError:
                payload = {"message": response.text}
            message = payload.get("message") or payload.get("error") or response.text
            if "Agent is not online" in str(message):
                message = (
                    "The current Maqsam agent is not online. "
                    "Open the Maqsam dialer, switch your agent status to online, then try again."
                )
            elif "Phone number is invalid" in str(message):
                message = (
                    "The destination phone number is invalid for Maqsam. "
                    "Use the full international format, for example 966XXXXXXXXX."
                )

            if response.status_code >= 500:
                frappe.log_error(
                    title="Maqsam API Server Error",
                    message=(
                        f"HTTP {response.status_code}\n"
                        f"Method: {method}\n"
                        f"Path: {path}\n"
                        f"Request ID: {request_id or 'N/A'}\n"
                        f"Response: {response.text}"
                    ),
                )
                message = (
                    "Maqsam returned an internal server error while processing the request. "
                    "This is coming from Maqsam's side."
                )

            if request_id:
                message = f"{message} (Request ID: {request_id})"
            frappe.throw(f"Maqsam API error {response.status_code}: {message}")

        try:
            return response.json()
        except ValueError:
            return response.text

    def test_connection(self) -> dict[str, Any]:
        agents = self.list_agents(page=0)
        contacts = self.list_contacts(page=1)
        return {
            "ok": True,
            "api_base": self.api_base,
            "agents_count": len(agents) if isinstance(agents, list) else None,
            "contacts_count": len(contacts.get("contact", [])) if isinstance(contacts, dict) else None,
        }

    def list_agents(self, page: int = 0) -> list[dict[str, Any]] | Any:
        path = "/v1/agents" if page in (0, 1) else f"/v1/agents/page/{page}"
        payload = self._request("GET", path)
        return payload.get("message", payload)

    def get_portal_url(self) -> str:
        return f"https://portal.{self.base_url}"

    def get_autologin_url(self, user_email: str, continue_path: str | None = None) -> str:
        payload = self._request(
            "POST",
            "/v2/token",
            form_payload={
                "UserEmail": user_email,
            },
        )

        result = payload.get("result", payload) if isinstance(payload, dict) else {}
        token = result.get("token") if isinstance(result, dict) else None
        if not token:
            frappe.throw("Maqsam Automatic Login token was not returned by the API.")

        query_params = {"auth_token": token}
        if continue_path not in (None, "", "/"):
            query_params["continue_path"] = continue_path

        return f"{self.get_portal_url()}/autologin?{urlencode(query_params)}"

    def get_agent_status(self, agent_email: str) -> dict[str, Any]:
        agents = self.list_agents(page=0)
        agent = None

        if isinstance(agents, list):
            agent = next(
                (
                    candidate
                    for candidate in agents
                    if str(candidate.get("email") or "").strip().lower() == agent_email.strip().lower()
                ),
                None,
            )

        if not agent:
            return {
                "found": False,
                "email": agent_email,
                "state": None,
                "active": None,
                "outgoing_enabled": None,
                "can_make_outbound_calls": False,
                "message": (
                    "The current Gain user email was not found among Maqsam agents. "
                    "Create or map this email in Maqsam first."
                ),
            }

        state = str(agent.get("state") or "").strip().lower()
        active = bool(agent.get("active"))
        outgoing_enabled = bool(agent.get("outgoingEnabled"))
        is_known_offline = state in KNOWN_OFFLINE_AGENT_STATES
        can_make_outbound_calls = active and outgoing_enabled and not is_known_offline

        if not active:
            message = "This Maqsam agent is inactive."
        elif not outgoing_enabled:
            message = "Outbound calling is disabled for this Maqsam agent."
        elif is_known_offline:
            message = (
                "This Maqsam agent is currently offline in the dialer. "
                "Open Maqsam and set the agent status to online before starting the call."
            )
        else:
            message = "This Maqsam agent appears ready for outbound calling."

        return {
            "found": True,
            "email": agent.get("email"),
            "name": agent.get("name"),
            "identifier": agent.get("identifier"),
            "state": state or None,
            "active": active,
            "outgoing_enabled": outgoing_enabled,
            "can_make_outbound_calls": can_make_outbound_calls,
            "message": message,
        }

    def list_contacts(self, page: int = 1) -> dict[str, Any]:
        payload = self._request("GET", "/v2/contacts", params={"page": page})
        return payload

    def list_calls(self, page: int = 1) -> list[dict[str, Any]] | Any:
        payload = self._request("GET", "/v2/calls", params={"page": page})
        return payload.get("message", payload)

    def get_available_caller_numbers(self, max_pages: int = 5) -> list[str]:
        # Maqsam's public API does not expose a dedicated registered-numbers endpoint
        # in the docs we reviewed, so we derive account numbers from recent call history.
        numbers: list[str] = []
        seen: set[str] = set()

        self._append_unique_number(numbers, seen, self.default_caller)

        for page in range(1, max_pages + 1):
            calls = self.list_calls(page=page)
            if not isinstance(calls, list) or not calls:
                break

            for call in calls:
                direction = str(call.get("direction") or call.get("type") or "").lower()

                if direction == "outbound":
                    candidates = [call.get("callerNumber"), call.get("caller")]
                elif direction == "inbound":
                    candidates = [call.get("calleeNumber"), call.get("callee")]
                else:
                    candidates = [
                        call.get("callerNumber"),
                        call.get("caller"),
                        call.get("calleeNumber"),
                        call.get("callee"),
                    ]

                for candidate in candidates:
                    self._append_unique_number(numbers, seen, candidate)

        return numbers

    def create_call(self, agent_email: str, phone: str, caller: str | None = None) -> dict[str, Any]:
        normalized_phone = self.normalize_outbound_phone(phone, caller=caller)
        payload = self._request(
            "POST",
            "/v2/calls",
            form_payload={
                "email": agent_email,
                "phone": normalized_phone,
                "caller": caller or self.default_caller,
            },
        )
        return payload

    def get_recording(self, call_id: str) -> tuple[bytes, str]:
        if not call_id:
            frappe.throw("Maqsam Call ID is required to fetch the recording.")

        try:
            response = self.session.get(
                url=f"{self.api_base}/v1/recording/{quote(str(call_id).strip())}",
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            frappe.throw(f"Maqsam recording download failed: {exc}")

        if not response.ok:
            request_id = response.headers.get("X-Request-Id")
            try:
                payload = response.json()
            except ValueError:
                payload = {"message": response.text}
            message = payload.get("message") or payload.get("error") or response.text
            if request_id:
                message = f"{message} (Request ID: {request_id})"
            frappe.throw(f"Maqsam recording API error {response.status_code}: {message}")

        return response.content, response.headers.get("Content-Type") or "audio/mpeg"

    def get_click_to_call_defaults(self) -> dict[str, Any]:
        caller_options = self.get_available_caller_numbers()
        return {
            "default_agent_email": self.default_agent_email or frappe.session.user,
            "default_caller": self.default_caller or (caller_options[0] if caller_options else ""),
            "caller_options": caller_options,
            "timeout_seconds": cint(self.timeout),
            "api_base": self.api_base,
            "portal_url": self.get_portal_url(),
        }


def get_client() -> MaqsamClient:
    return MaqsamClient()
