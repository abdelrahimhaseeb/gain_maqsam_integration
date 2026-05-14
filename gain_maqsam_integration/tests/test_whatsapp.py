from __future__ import annotations

import json
import re
import unittest
from unittest.mock import patch

import frappe

from gain_maqsam_integration.permissions import MAQSAM_AGENT_ROLE, MAQSAM_SUPERVISOR_ROLE
from gain_maqsam_integration.maqsam_whatsapp import api as whatsapp_api
from gain_maqsam_integration.maqsam_whatsapp.api import (
    maqsam_whatsapp_get_conversation,
    maqsam_whatsapp_list_templates,
    maqsam_whatsapp_send_template,
)
from gain_maqsam_integration.maqsam_whatsapp.client import MaqsamWhatsAppClient


class FakeWhatsAppClient:
    def __init__(self, templates=None, conversation_payload=None, send_response_extra=None):
        self.templates = templates if templates is not None else []
        self.conversation_payload = conversation_payload or {"status": "open", "messages": []}
        self.send_response_extra = dict(send_response_extra or {})
        self.sent: list[dict] = []
        self.requested_conversations: list[str] = []
        self.list_templates_calls = 0

    def normalize_phone(self, phone: str) -> str:
        return re.sub(r"\D", "", phone or "")

    def normalize_whatsapp_phone(self, phone: str) -> str:
        digits = re.sub(r"\D", "", phone or "")
        return f"+{digits}" if digits else ""

    def list_templates(self):
        self.list_templates_calls += 1
        return {"templates": self.templates}

    def send_template_message(self, **kwargs):
        self.sent.append(kwargs)
        response = {
            "message_id": f"msg-{len(self.sent)}",
            "conversation_id": f"conv-{len(self.sent)}-{frappe.generate_hash(length=6)}",
            "status": "sent",
        }
        response.update(self.send_response_extra)
        return response

    def get_conversation(self, conversation_id: str):
        self.requested_conversations.append(conversation_id)
        payload = dict(self.conversation_payload)
        payload.setdefault("conversation_id", conversation_id)
        return payload


class RecordingBaseClient:
    def __init__(self):
        self.calls: list[dict] = []

    def normalize_outbound_phone(self, phone: str) -> str:
        digits = re.sub(r"\D", "", phone or "")
        if digits.startswith("05") and len(digits) == 10:
            return f"966{digits[1:]}"
        return digits

    def _request(self, method, path, **kwargs):
        self.calls.append({"method": method, "path": path, "kwargs": kwargs})
        return {"ok": True}


def ensure_role(role_name: str) -> None:
    if frappe.db.exists("Role", role_name):
        return
    frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1}).insert(ignore_permissions=True)


def ensure_whatsapp_doctypes() -> None:
    if not frappe.db.exists("Module Def", "Maqsam WhatsApp"):
        frappe.get_doc(
            {
                "doctype": "Module Def",
                "module_name": "Maqsam WhatsApp",
                "app_name": "gain_maqsam_integration",
            }
        ).insert(ignore_permissions=True)

    frappe.local.module_app = frappe.local.module_app or {}
    frappe.local.app_modules = frappe.local.app_modules or {}
    frappe.local.module_app["maqsam_whatsapp"] = "gain_maqsam_integration"
    frappe.local.app_modules.setdefault("gain_maqsam_integration", [])
    if "maqsam_whatsapp" not in frappe.local.app_modules["gain_maqsam_integration"]:
        frappe.local.app_modules["gain_maqsam_integration"].append("maqsam_whatsapp")

    for doctype in (
        "maqsam_whatsapp_template",
        "maqsam_whatsapp_conversation",
        "maqsam_whatsapp_message",
    ):
        frappe.reload_doc("maqsam_whatsapp", "doctype", doctype, force=True)
    frappe.db.commit()


class TestMaqsamWhatsAppBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        if not frappe.db.exists("DocType", "Maqsam Settings"):
            raise unittest.SkipTest("Maqsam Settings doctype not installed")
        ensure_role(MAQSAM_AGENT_ROLE)
        ensure_role(MAQSAM_SUPERVISOR_ROLE)
        ensure_whatsapp_doctypes()

    def setUp(self):
        frappe.set_user("Administrator")
        self.original_enabled = frappe.db.get_single_value("Maqsam Settings", "enabled")
        frappe.db.set_single_value("Maqsam Settings", "enabled", 1)
        self.created_users: list[str] = []
        self.created_messages: list[str] = []
        self.created_conversations: list[str] = []
        self.created_templates: list[str] = []
        self.created_leads: list[str] = []
        self.agent = self._make_user("agent", [MAQSAM_AGENT_ROLE])
        self.supervisor = self._make_user("supervisor", [MAQSAM_SUPERVISOR_ROLE])
        frappe.db.commit()

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.set_single_value("Maqsam Settings", "enabled", self.original_enabled or 0)
        for name in self.created_messages:
            if name and frappe.db.exists("Maqsam WhatsApp Message", name):
                frappe.delete_doc("Maqsam WhatsApp Message", name, ignore_permissions=True, force=True)
        for name in self.created_conversations:
            if name and frappe.db.exists("Maqsam WhatsApp Conversation", name):
                frappe.delete_doc("Maqsam WhatsApp Conversation", name, ignore_permissions=True, force=True)
        for name in self.created_templates:
            if name and frappe.db.exists("Maqsam WhatsApp Template", name):
                frappe.delete_doc("Maqsam WhatsApp Template", name, ignore_permissions=True, force=True)
        for lead in self.created_leads:
            if frappe.db.exists("Lead", lead):
                frappe.delete_doc("Lead", lead, ignore_permissions=True, force=True)
        for user in self.created_users:
            if frappe.db.exists("User", user):
                frappe.delete_doc("User", user, ignore_permissions=True, force=True)
        frappe.db.commit()

    def _make_user(self, label: str, roles: list[str]) -> str:
        email = f"maqsam-whatsapp-{label}-{frappe.generate_hash(length=8)}@example.com"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Maqsam",
                "last_name": f"WhatsApp {label.title()}",
                "enabled": 1,
                "send_welcome_email": 0,
                "roles": [{"role": role} for role in roles],
            }
        ).insert(ignore_permissions=True)
        self.created_users.append(email)
        return email

    def _make_template(self, template_id: str, status: str = "approved", active: int = 1) -> str:
        doc = frappe.get_doc(
            {
                "doctype": "Maqsam WhatsApp Template",
                "template_id": template_id,
                "template_name": template_id,
                "identity_number": f"identity-{template_id}",
                "active": active,
                "status": status,
                "language": "ar",
                "category": "utility",
            }
        )
        doc.insert(ignore_permissions=True)
        self.created_templates.append(doc.name)
        return doc.name

    def _make_conversation(self, conversation_id: str, sent_by_user: str) -> str:
        doc = frappe.get_doc(
            {
                "doctype": "Maqsam WhatsApp Conversation",
                "conversation_id": conversation_id,
                "status": "open",
                "sent_by_user": sent_by_user,
            }
        )
        doc.insert(ignore_permissions=True)
        self.created_conversations.append(doc.name)
        return doc.name

    def _make_lead(self) -> str:
        doc = frappe.get_doc(
            {
                "doctype": "Lead",
                "lead_name": f"WhatsApp Lead {frappe.generate_hash(length=6)}",
                "mobile_no": "+966500000003",
            }
        )
        doc.insert(ignore_permissions=True)
        self.created_leads.append(doc.name)
        return doc.name

    def test_client_send_payload_uses_official_fields_and_plus_phone(self):
        base = RecordingBaseClient()
        client = MaqsamWhatsAppClient(base_client=base)

        client.send_template_message(
            phone="0500000002",
            template_id="tpl-official",
            variables={"name": "Patient"},
            language="ar",
            conversation_id="conv-ignored",
        )

        self.assertEqual(len(base.calls), 1)
        payload = base.calls[0]["kwargs"]["form_payload"]
        self.assertEqual(set(payload), {"RecipientPhone", "TemplateId", "TemplateVariables"})
        self.assertEqual(payload["RecipientPhone"], "+966500000002")
        self.assertEqual(payload["TemplateId"], "tpl-official")
        self.assertEqual(json.loads(payload["TemplateVariables"]), {"name": "Patient"})
        self.assertNotIn("Language", payload)
        self.assertNotIn("ConversationId", payload)

    def test_supervisor_can_force_template_sync_but_response_is_safe(self):
        template_id = f"tpl-{frappe.generate_hash(length=8)}"
        fake = FakeWhatsAppClient(
            templates=[
                {
                    "id": template_id,
                    "name": "appointment_reminder",
                    "identityNumber": "ID-123",
                    "active": True,
                    "language": "ar",
                    "status": "approved",
                    "category": "utility",
                    "createdAt": "2026-05-01 10:00:00",
                    "content": "Hello {{1}}",
                    "provider_secret": "do-not-return",
                }
            ]
        )

        frappe.set_user(self.supervisor)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake):
            result = maqsam_whatsapp_list_templates(sync=1)

        self.assertTrue(result["ok"])
        self.assertEqual(result["synced"], 1)
        self.assertEqual(fake.list_templates_calls, 1)
        self.assertTrue(frappe.db.exists("Maqsam WhatsApp Template", {"template_id": template_id}))
        self.created_templates.append(template_id)
        template = frappe.get_doc("Maqsam WhatsApp Template", template_id)
        self.assertEqual(template.active, 1)
        self.assertEqual(template.identity_number, "ID-123")
        self.assertTrue(template.maqsam_created_at)
        serialized = json.dumps(result, default=str)
        self.assertIn(template_id, serialized)
        self.assertNotIn("raw_payload", serialized)
        self.assertNotIn("provider_secret", serialized)

    def test_agent_lists_local_approved_active_templates_without_external_sync(self):
        active_template = self._make_template("tpl-local-active")
        self._make_template("tpl-local-pending", status="pending", active=1)
        self._make_template("tpl-local-inactive", status="approved", active=0)
        fake = FakeWhatsAppClient(templates=[{"id": "tpl-remote", "status": "approved", "active": True}])

        frappe.set_user(self.agent)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake):
            result = maqsam_whatsapp_list_templates()

        template_ids = {row["template_id"] for row in result["templates"]}
        self.assertIn(active_template, template_ids)
        self.assertNotIn("tpl-local-pending", template_ids)
        self.assertNotIn("tpl-local-inactive", template_ids)
        self.assertNotIn("tpl-remote", template_ids)
        self.assertEqual(fake.list_templates_calls, 0)
        self.assertEqual(result["synced"], 0)
        serialized = json.dumps(result, default=str)
        self.assertNotIn("raw_payload", serialized)

    def test_agent_cannot_force_template_sync(self):
        fake = FakeWhatsAppClient(templates=[{"id": "tpl-remote", "status": "approved", "active": True}])

        frappe.set_user(self.agent)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake):
            with self.assertRaises(frappe.PermissionError):
                maqsam_whatsapp_list_templates(sync=1)

        self.assertEqual(fake.list_templates_calls, 0)

    def test_disabled_integration_blocks_all_whatsapp_apis_before_network(self):
        fake = FakeWhatsAppClient()
        self._make_template("tpl-disabled")
        frappe.db.set_single_value("Maqsam Settings", "enabled", 0)
        frappe.db.commit()

        frappe.set_user(self.supervisor)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake):
            with self.assertRaises(frappe.PermissionError):
                maqsam_whatsapp_list_templates()
            with self.assertRaises(frappe.PermissionError):
                maqsam_whatsapp_send_template(template_id="tpl-disabled", phone="+966500000002")
            with self.assertRaises(frappe.PermissionError):
                maqsam_whatsapp_get_conversation("conv-disabled")

        self.assertEqual(fake.list_templates_calls, 0)
        self.assertEqual(fake.sent, [])
        self.assertEqual(fake.requested_conversations, [])

    def test_agent_direct_phone_send_is_denied(self):
        fake = FakeWhatsAppClient()
        self._make_template("tpl-direct")
        frappe.set_user(self.agent)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake):
            with self.assertRaises(frappe.PermissionError):
                maqsam_whatsapp_send_template(template_id="tpl-direct", phone="+966500000001")
        self.assertEqual(fake.sent, [])

    def test_supervisor_direct_phone_send_is_allowed_and_audited(self):
        fake = FakeWhatsAppClient()
        self._make_template("tpl-supervisor")
        frappe.set_user(self.supervisor)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake):
            result = maqsam_whatsapp_send_template(
                template_id="tpl-supervisor",
                phone="+966500000002",
                variables={"name": "Patient"},
                language="ar",
                conversation_id="conv-not-sent",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(fake.sent[0]["phone"], "+966500000002")
        self.assertNotIn("language", fake.sent[0])
        self.assertNotIn("conversation_id", fake.sent[0])
        self.created_messages.append(result["message"])
        self.created_conversations.append(result["conversation"])
        message = frappe.get_doc("Maqsam WhatsApp Message", result["message"])
        self.assertEqual(message.status, "Sent")
        self.assertEqual(message.sent_by_user, self.supervisor)
        self.assertEqual(message.template_id, "tpl-supervisor")
        self.assertIn("RecipientPhone", message.request_payload)
        self.assertIn("tpl-supervisor", message.request_payload)
        self.assertIn("msg-1", message.response_payload)

    def test_send_response_is_sanitized_but_raw_response_is_audited(self):
        fake = FakeWhatsAppClient(
            send_response_extra={
                "message_status": "delivered",
                "provider_secret": "do-not-return",
                "unknown_provider_field": {"nested": "hidden"},
            }
        )
        self._make_template("tpl-sanitized-send")
        frappe.set_user(self.supervisor)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake):
            result = maqsam_whatsapp_send_template(
                template_id="tpl-sanitized-send",
                phone="+966500000009",
            )

        self.assertTrue(result["ok"])
        self.assertNotIn("response", result)
        serialized = json.dumps(result, default=str)
        self.assertNotIn("provider_secret", serialized)
        self.assertNotIn("unknown_provider_field", serialized)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["message_status"], "delivered")
        self.created_messages.append(result["message"])
        self.created_conversations.append(result["conversation"])
        raw_response = frappe.db.get_value("Maqsam WhatsApp Message", result["message"], "response_payload")
        self.assertIn("provider_secret", raw_response)
        self.assertIn("unknown_provider_field", raw_response)

    def test_agent_can_send_for_readable_reference_record(self):
        fake = FakeWhatsAppClient()
        self._make_template("tpl-agent")
        lead_name = self._make_lead()
        frappe.set_user(self.agent)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake), patch(
            "gain_maqsam_integration.maqsam_whatsapp.api.can_read_document",
            return_value=True,
        ), patch(
            "gain_maqsam_integration.maqsam_whatsapp.api._get_reference_phone_candidates",
            return_value=["+966500000003"],
        ):
            result = maqsam_whatsapp_send_template(
                template_id="tpl-agent",
                reference_doctype="Lead",
                reference_name=lead_name,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(fake.sent[0]["phone"], "+966500000003")
        self.created_messages.append(result["message"])
        self.created_conversations.append(result["conversation"])

    def test_agent_cannot_override_readable_reference_with_unrelated_phone(self):
        fake = FakeWhatsAppClient()
        self._make_template("tpl-agent")
        frappe.set_user(self.agent)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake), patch(
            "gain_maqsam_integration.maqsam_whatsapp.api.can_read_document",
            return_value=True,
        ), patch(
            "gain_maqsam_integration.maqsam_whatsapp.api._get_reference_phone_candidates",
            return_value=["+966500000004"],
        ):
            with self.assertRaises(frappe.PermissionError):
                maqsam_whatsapp_send_template(
                    template_id="tpl-agent",
                    phone="+966599999999",
                    reference_doctype="Lead",
                    reference_name="LEAD-TEST",
                )
        self.assertEqual(fake.sent, [])

    def test_agent_cannot_send_for_disallowed_reference_doctype_even_if_readable(self):
        fake = FakeWhatsAppClient()
        self._make_template("tpl-agent-user")
        frappe.set_user(self.agent)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake), patch(
            "gain_maqsam_integration.maqsam_whatsapp.api.can_read_document",
            return_value=True,
        ), patch(
            "gain_maqsam_integration.maqsam_whatsapp.api._get_reference_phone_candidates",
            return_value=["+966500000004"],
        ):
            with self.assertRaises(frappe.PermissionError):
                maqsam_whatsapp_send_template(
                    template_id="tpl-agent-user",
                    reference_doctype="User",
                    reference_name=self.agent,
                )
        self.assertEqual(fake.sent, [])

    def test_unapproved_or_inactive_template_cannot_send(self):
        fake = FakeWhatsAppClient()
        self._make_template("tpl-pending", status="pending", active=1)
        self._make_template("tpl-inactive", status="approved", active=0)

        frappe.set_user(self.supervisor)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake):
            with self.assertRaises(frappe.PermissionError):
                maqsam_whatsapp_send_template(template_id="tpl-pending", phone="+966500000005")
            with self.assertRaises(frappe.PermissionError):
                maqsam_whatsapp_send_template(template_id="tpl-inactive", phone="+966500000006")

        self.assertEqual(fake.sent, [])

    def test_agent_unknown_conversation_lookup_is_denied_before_network(self):
        fake = FakeWhatsAppClient()
        frappe.set_user(self.agent)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake):
            with self.assertRaises(frappe.PermissionError):
                maqsam_whatsapp_get_conversation("conv-unknown")
        self.assertEqual(fake.requested_conversations, [])

    def test_agent_conversation_response_is_sanitized_and_raw_stays_local(self):
        conversation_id = f"conv-agent-{frappe.generate_hash(length=8)}"
        local_name = self._make_conversation(conversation_id, self.agent)
        fake = FakeWhatsAppClient(
            conversation_payload={
                "status": "open",
                "secret_token": "do-not-leak",
                "messages": [
                    {
                        "id": "m1",
                        "direction": "outbound",
                        "status": "sent",
                        "content": "Appointment reminder",
                        "provider_secret": "hidden",
                    }
                ],
            }
        )

        frappe.set_user(self.agent)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake):
            result = maqsam_whatsapp_get_conversation(conversation_id)

        self.assertTrue(result["ok"])
        self.assertEqual(result["conversation"], local_name)
        self.assertNotIn("response", result)
        serialized = json.dumps(result, default=str)
        self.assertNotIn("secret_token", serialized)
        self.assertNotIn("provider_secret", serialized)
        self.assertEqual(result["messages"][0]["content"], "Appointment reminder")
        raw_payload = frappe.db.get_value("Maqsam WhatsApp Conversation", local_name, "raw_payload")
        self.assertIn("secret_token", raw_payload)

    def test_supervisor_direct_conversation_lookup_is_allowed_and_sanitized(self):
        fake = FakeWhatsAppClient(conversation_payload={"status": "open", "messages": [{"id": "m1", "text": "hello", "secret": "hidden"}]})
        conversation_id = f"conv-supervisor-{frappe.generate_hash(length=8)}"
        frappe.set_user(self.supervisor)
        with patch("gain_maqsam_integration.maqsam_whatsapp.api.get_client", return_value=fake):
            result = maqsam_whatsapp_get_conversation(conversation_id)

        self.assertTrue(result["ok"])
        self.assertEqual(fake.requested_conversations, [conversation_id])
        self.created_conversations.append(result["conversation"])
        self.assertTrue(frappe.db.exists("Maqsam WhatsApp Conversation", result["conversation"]))
        self.assertNotIn("response", result)
        self.assertNotIn("secret", json.dumps(result, default=str))
        self.assertEqual(result["messages"][0]["content"], "hello")

    def test_unsupported_whatsapp_features_are_not_exposed(self):
        self.assertFalse(hasattr(whatsapp_api, "maqsam_whatsapp_list_conversations"))
        self.assertFalse(hasattr(whatsapp_api, "maqsam_whatsapp_receive_delivery_status"))
        self.assertFalse(hasattr(whatsapp_api, "maqsam_whatsapp_send_freeform_message"))
