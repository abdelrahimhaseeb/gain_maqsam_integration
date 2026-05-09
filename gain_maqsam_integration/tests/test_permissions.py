from __future__ import annotations

import unittest
from time import time
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime, today

from gain_maqsam_integration.api import (
    _only_maqsam_user,
    maqsam_get_call_recording,
    maqsam_get_caller_profile,
    maqsam_get_current_call_profile,
    maqsam_save_call_recording,
    maqsam_update_call_outcome,
)
from gain_maqsam_integration.gain_maqsam_integration.report.agent_performance_daily.agent_performance_daily import (
    execute as execute_agent_performance_daily,
)
from gain_maqsam_integration.gain_maqsam_integration.report.call_to_appointment_conversion.call_to_appointment_conversion import (
    execute as execute_call_to_appointment_conversion,
)
from gain_maqsam_integration.permissions import (
    MAQSAM_AGENT_ROLE,
    MAQSAM_SUPERVISOR_ROLE,
    can_access_call_log,
    enforce_call_log_access,
    get_call_log_report_scope,
)
from gain_maqsam_integration.profile import appointments, invoices, matcher


def ensure_role(role_name: str) -> None:
    if frappe.db.exists("Role", role_name):
        return
    frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1}).insert(ignore_permissions=True)


class FakeMeta:
    def __init__(self, fields: list[str]):
        self.fields = set(fields)

    def has_field(self, fieldname: str) -> bool:
        return fieldname in self.fields


class TestMaqsamApiPermissions(unittest.TestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        ensure_role(MAQSAM_AGENT_ROLE)
        ensure_role(MAQSAM_SUPERVISOR_ROLE)
        self.user = f"maqsam-desk-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": self.user,
                "first_name": "Maqsam",
                "last_name": "Desk Test",
                "enabled": 1,
                "send_welcome_email": 0,
                "roles": [{"role": "Desk User"}],
            }
        )
        user.insert(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        frappe.set_user("Administrator")
        if frappe.db.exists("User", self.user):
            frappe.delete_doc("User", self.user, ignore_permissions=True, force=True)
        frappe.db.commit()

    def test_desk_user_is_blocked_from_maqsam_apis(self):
        frappe.set_user(self.user)
        with self.assertRaises(frappe.PermissionError):
            _only_maqsam_user()
        with self.assertRaises(frappe.PermissionError):
            maqsam_get_caller_profile(phone="+966500000001")

    def test_maqsam_manager_is_allowed(self):
        manager = f"maqsam-manager-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": manager,
                "first_name": "Maqsam",
                "last_name": "Manager Test",
                "enabled": 1,
                "send_welcome_email": 0,
                "roles": [{"role": "System Manager"}, {"role": MAQSAM_AGENT_ROLE}],
            }
        )
        user.insert(ignore_permissions=True)
        try:
            frappe.set_user(manager)
            _only_maqsam_user()
        finally:
            frappe.set_user("Administrator")
            frappe.delete_doc("User", manager, ignore_permissions=True, force=True)

    def test_maqsam_supervisor_is_allowed(self):
        supervisor = f"maqsam-supervisor-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": supervisor,
                "first_name": "Maqsam",
                "last_name": "Supervisor Test",
                "enabled": 1,
                "send_welcome_email": 0,
                "roles": [{"role": MAQSAM_SUPERVISOR_ROLE}],
            }
        )
        user.insert(ignore_permissions=True)
        try:
            frappe.set_user(supervisor)
            _only_maqsam_user()
        finally:
            frappe.set_user("Administrator")
            frappe.delete_doc("User", supervisor, ignore_permissions=True, force=True)


class TestMaqsamCallLogOwnership(unittest.TestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        ensure_role(MAQSAM_AGENT_ROLE)
        ensure_role(MAQSAM_SUPERVISOR_ROLE)
        self.created_users: list[str] = []
        self.created_logs: list[str] = []
        self.agent_owner = self._make_user("owner", [MAQSAM_AGENT_ROLE])
        self.agent_other = self._make_user("other", [MAQSAM_AGENT_ROLE])
        self.supervisor = self._make_user("supervisor", [MAQSAM_SUPERVISOR_ROLE])
        self.system_manager = self._make_user("manager", ["System Manager"])

        digits = "".join(str(ord(char) % 10) for char in frappe.generate_hash(length=12))
        self.owner_phone = f"+966500{digits[:6]}"
        self.other_phone = f"+966599{digits[6:12]}"
        self.call_log = self._make_call_log(
            self.agent_owner, self.owner_phone, f"perm-owner-{frappe.generate_hash(length=8)}", "Answered", 45
        )
        self.other_call_log = self._make_call_log(
            self.agent_other, self.other_phone, f"perm-other-{frappe.generate_hash(length=8)}", "Busy", 15
        )
        frappe.db.commit()

    def tearDown(self):
        frappe.set_user("Administrator")
        for name in self.created_logs:
            if frappe.db.exists("Maqsam Call Log", name):
                frappe.delete_doc("Maqsam Call Log", name, ignore_permissions=True, force=True)
        for user in self.created_users:
            if frappe.db.exists("User", user):
                frappe.delete_doc("User", user, ignore_permissions=True, force=True)
        frappe.db.commit()

    def _make_user(self, label: str, roles: list[str]) -> str:
        email = f"maqsam-{label}-{frappe.generate_hash(length=8)}@example.com"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Maqsam",
                "last_name": label.title(),
                "enabled": 1,
                "send_welcome_email": 0,
                "roles": [{"role": role} for role in roles],
            }
        ).insert(ignore_permissions=True)
        self.created_users.append(email)
        return email

    def _make_call_log(
        self,
        agent_email: str,
        phone: str,
        call_id: str,
        outcome: str = "Answered",
        duration: int = 30,
        state: str = "ended",
        direction: str = "inbound",
        timestamp=None,
    ) -> str:
        doc = frappe.get_doc(
            {
                "doctype": "Maqsam Call Log",
                "source": "Maqsam Sync",
                "direction": direction,
                "state": state,
                "outcome": outcome,
                "maqsam_call_id": call_id,
                "timestamp": timestamp or now_datetime(),
                "duration": duration,
                "agent_email": agent_email,
                "caller_number": phone,
                "callee_number": "+966112223344",
                "normalized_phone": phone,
            }
        )
        doc.insert(ignore_permissions=True)
        self.created_logs.append(doc.name)
        return doc.name

    def test_owner_agent_can_access_own_call_log(self):
        frappe.set_user(self.agent_owner)
        self.assertTrue(can_access_call_log(self.call_log, ptype="read"))
        self.assertEqual(enforce_call_log_access(self.call_log, "read").name, self.call_log)

    def test_agent_cannot_access_another_agents_call_log(self):
        frappe.set_user(self.agent_other)
        self.assertFalse(can_access_call_log(self.call_log, ptype="read"))
        with self.assertRaises(frappe.PermissionError):
            enforce_call_log_access(self.call_log, "read")

    def test_agent_cannot_update_another_agents_call_log(self):
        frappe.set_user(self.agent_other)
        with self.assertRaises(frappe.PermissionError):
            enforce_call_log_access(self.call_log, "write")
        with self.assertRaises(frappe.PermissionError):
            maqsam_update_call_outcome(self.call_log, outcome="Follow Up", notes="blocked")

    def test_agent_cannot_directly_save_call_log_fields(self):
        frappe.set_user(self.agent_owner)
        doc = frappe.get_doc("Maqsam Call Log", self.call_log)
        doc.state = "tampered"
        with self.assertRaises(frappe.PermissionError):
            doc.save()
        frappe.db.rollback()

    def test_agent_business_update_still_works_through_whitelisted_method(self):
        frappe.set_user(self.agent_owner)
        result = maqsam_update_call_outcome(
            self.call_log,
            outcome="Follow Up",
            notes="call back",
            follow_up_required=1,
            follow_up_date=today(),
        )
        self.assertTrue(result["ok"])
        values = frappe.db.get_value(
            "Maqsam Call Log",
            self.call_log,
            ["outcome", "notes", "follow_up_required", "follow_up_date"],
            as_dict=True,
        )
        self.assertEqual(values.outcome, "Follow Up")
        self.assertIn("call back", values.notes)
        self.assertEqual(values.follow_up_required, 1)

    def test_supervisor_can_access_org_wide_call_log(self):
        frappe.set_user(self.supervisor)
        self.assertTrue(can_access_call_log(self.call_log, ptype="read"))
        self.assertEqual(enforce_call_log_access(self.call_log, "read").name, self.call_log)

    def test_system_manager_can_access_org_wide_call_log(self):
        frappe.set_user(self.system_manager)
        self.assertTrue(can_access_call_log(self.call_log, ptype="read"))
        self.assertTrue(can_access_call_log(self.other_call_log, ptype="read"))
        self.assertEqual(enforce_call_log_access(self.other_call_log, "read").name, self.other_call_log)

    def test_agent_report_scope_is_limited_to_their_agent_email(self):
        frappe.set_user(self.agent_owner)
        condition, params = get_call_log_report_scope()
        self.assertIn("agent_email", condition)
        self.assertEqual(params["maqsam_agent_emails"], (self.agent_owner,))

    def test_supervisor_and_system_manager_report_scope_is_org_wide(self):
        frappe.set_user(self.supervisor)
        condition, params = get_call_log_report_scope()
        self.assertEqual(condition, "")
        self.assertEqual(params, {})

        frappe.set_user(self.system_manager)
        condition, params = get_call_log_report_scope()
        self.assertEqual(condition, "")
        self.assertEqual(params, {})

    def test_agent_performance_report_scopes_rows_by_role(self):
        filters = {"from_date": today(), "to_date": today()}

        frappe.set_user(self.agent_owner)
        _columns, data = execute_agent_performance_daily(filters)
        agent_rows = {row.agent_email for row in data}
        self.assertIn(self.agent_owner, agent_rows)
        self.assertNotIn(self.agent_other, agent_rows)

        frappe.set_user(self.supervisor)
        _columns, data = execute_agent_performance_daily(filters)
        supervisor_rows = {row.agent_email for row in data}
        self.assertIn(self.agent_owner, supervisor_rows)
        self.assertIn(self.agent_other, supervisor_rows)

        frappe.set_user(self.system_manager)
        _columns, data = execute_agent_performance_daily(filters)
        manager_rows = {row.agent_email for row in data}
        self.assertIn(self.agent_owner, manager_rows)
        self.assertIn(self.agent_other, manager_rows)

    def test_agent_cannot_run_call_to_appointment_conversion_report(self):
        frappe.set_user(self.agent_owner)
        with self.assertRaises(frappe.PermissionError):
            execute_call_to_appointment_conversion({"from_date": today(), "to_date": today()})

    def test_agent_direct_phone_lookup_requires_call_context(self):
        frappe.set_user(self.agent_owner)
        with self.assertRaises(frappe.PermissionError):
            maqsam_get_caller_profile(phone=self.owner_phone)

    def test_supervisor_direct_phone_lookup_is_allowed(self):
        frappe.set_user(self.supervisor)
        profile = maqsam_get_caller_profile(phone=self.owner_phone)
        self.assertEqual(profile["profile_summary"]["input_phone"], self.owner_phone)

    def test_system_manager_direct_phone_lookup_is_allowed(self):
        frappe.set_user(self.system_manager)
        profile = maqsam_get_caller_profile(phone=self.owner_phone)
        self.assertEqual(profile["profile_summary"]["input_phone"], self.owner_phone)

    def test_owner_agent_can_use_owned_call_log_for_profile(self):
        frappe.set_user(self.agent_owner)
        profile = maqsam_get_caller_profile(call_log=self.call_log)
        self.assertEqual(profile["profile_summary"]["input_phone"], self.owner_phone)

    def test_agent_can_open_shared_active_inbound_current_call_profile(self):
        active_log = self._make_call_log(
            self.agent_owner,
            self.owner_phone,
            f"perm-current-{frappe.generate_hash(length=8)}",
            "",
            0,
            state="ringing",
            timestamp=add_to_date(now_datetime(), minutes=1),
        )
        frappe.db.commit()

        frappe.set_user(self.agent_other)
        with self.assertRaises(frappe.PermissionError):
            maqsam_get_caller_profile(call_log=active_log)

        current = maqsam_get_current_call_profile(sync=0)
        self.assertEqual(current["call_log"], active_log)
        self.assertEqual(current["phone"], self.owner_phone)
        self.assertTrue(current["active"])
        self.assertEqual(current["profile"]["profile_summary"]["input_phone"], self.owner_phone)

    def test_agent_can_open_latest_recent_inbound_profile_when_call_already_terminal(self):
        recent_log = self._make_call_log(
            self.agent_owner,
            self.owner_phone,
            f"perm-recent-{frappe.generate_hash(length=8)}",
            "No Answer",
            17,
            state="abandoned",
            timestamp=add_to_date(now_datetime(), minutes=1),
        )
        frappe.db.commit()

        frappe.set_user(self.agent_other)
        current = maqsam_get_current_call_profile(sync=0)

        self.assertEqual(current["call_log"], recent_log)
        self.assertEqual(current["phone"], self.owner_phone)
        self.assertFalse(current["active"])
        self.assertEqual(current["profile"]["profile_summary"]["input_phone"], self.owner_phone)

    def test_current_profile_uses_raw_recent_maqsam_call_timestamp_after_sync(self):
        call_id = f"perm-raw-recent-{frappe.generate_hash(length=8)}"
        phone = f"+966500{frappe.generate_hash(length=6)}"
        raw_call = {
            "id": call_id,
            "direction": "inbound",
            "type": "inbound",
            "caller": phone,
            "callee": "+966115200879",
            "callerNumber": phone,
            "calleeNumber": "+966115200879",
            "state": "abandoned",
            "timestamp": int(time()),
            "duration": 5,
            "agents": [{"email": self.agent_owner, "name": "Owner"}],
        }

        class FakeClient:
            def list_calls(self, page=1):
                return [raw_call]

        frappe.set_user(self.agent_other)
        with patch("gain_maqsam_integration.api.get_client", return_value=FakeClient()):
            current = maqsam_get_current_call_profile(sync=1)

        if current.get("call_log"):
            self.created_logs.append(current["call_log"])

        self.assertEqual(current["maqsam_call_id"], call_id)
        self.assertEqual(current["phone"], phone)
        self.assertFalse(current["active"])
        self.assertEqual(current["profile"]["profile_summary"]["input_phone"], phone)

    def test_agent_raw_maqsam_fallback_without_call_log_is_not_profile_lookup(self):
        raw_call = {
            "id": f"perm-raw-nosync-{frappe.generate_hash(length=8)}",
            "direction": "inbound",
            "caller": self.owner_phone,
            "callee": "+966115200879",
            "state": "ringing",
            "timestamp": int(time()),
        }

        class FakeClient:
            def list_calls(self, page=1):
                return [raw_call]

        frappe.set_user(self.agent_other)
        with patch("gain_maqsam_integration.api.get_client", return_value=FakeClient()), patch(
            "gain_maqsam_integration.api.sync_recent_calls",
            return_value={"created": 0, "updated": 0, "logs": [], "created_inbound": []},
        ), patch("gain_maqsam_integration.api._find_current_call_context_from_logs", return_value={}):
            current = maqsam_get_current_call_profile(sync=1)

        self.assertEqual(current, {})

    def test_caller_profile_recent_calls_exclude_unowned_call_logs(self):
        hidden_log = self._make_call_log(
            self.agent_other,
            self.owner_phone,
            f"perm-hidden-{frappe.generate_hash(length=8)}",
            "Answered",
            20,
        )
        frappe.db.commit()

        frappe.set_user(self.agent_owner)
        profile = maqsam_get_caller_profile(call_log=self.call_log)
        recent_call_names = {row.get("name") for row in profile["recent_calls"]}
        self.assertIn(self.call_log, recent_call_names)
        self.assertNotIn(hidden_log, recent_call_names)

    def test_agent_cannot_fetch_save_or_download_another_agents_recording(self):
        frappe.set_user(self.agent_other)
        with self.assertRaises(frappe.PermissionError):
            maqsam_get_call_recording(self.call_log)
        with self.assertRaises(frappe.PermissionError):
            maqsam_get_call_recording(self.call_log, download=1)
        with self.assertRaises(frappe.PermissionError):
            maqsam_save_call_recording(self.call_log)

    def test_agent_cannot_bypass_direct_lookup_with_missing_maqsam_call_id(self):
        frappe.set_user(self.agent_owner)
        with self.assertRaises(frappe.PermissionError):
            maqsam_get_caller_profile(
                phone=self.owner_phone,
                maqsam_call_id=f"missing-{frappe.generate_hash(length=8)}",
            )


class TestCallerProfilePermissionFiltering(unittest.TestCase):
    def test_matcher_filters_unauthorized_patient_matches(self):
        patient_row = frappe._dict(
            {
                "name": "PAT-UNAUTHORIZED",
                "mobile": "+966500111222",
                "patient_name": "Hidden Patient",
                "status": "Active",
            }
        )

        def exists(doctype, name=None):
            return doctype == "DocType" and name == "Patient"

        def get_all(doctype, **kwargs):
            return [patient_row] if doctype == "Patient" else []

        with patch.object(matcher.frappe.db, "exists", side_effect=exists), patch.object(
            matcher.frappe, "get_meta", return_value=FakeMeta(["mobile", "patient_name", "status"])
        ), patch.object(matcher.frappe, "get_all", side_effect=get_all), patch.object(
            matcher, "can_read_document", return_value=False
        ):
            self.assertEqual(matcher.find_matches("+966500111222"), [])

    def test_invoice_summary_filters_unauthorized_sales_invoices(self):
        invoice_row = frappe._dict(
            {
                "name": "SINV-UNAUTHORIZED",
                "customer": "CUST-1",
                "customer_name": "Hidden Customer",
                "posting_date": today(),
                "due_date": today(),
                "grand_total": 100,
                "outstanding_amount": 100,
                "status": "Unpaid",
                "docstatus": 1,
            }
        )

        def can_read(doctype, name, user=None):
            return doctype == "Customer" and name == "CUST-1"

        with patch.object(invoices.frappe.db, "exists", return_value=True), patch.object(
            invoices.frappe,
            "get_meta",
            return_value=FakeMeta(
                [
                    "customer",
                    "customer_name",
                    "posting_date",
                    "due_date",
                    "grand_total",
                    "outstanding_amount",
                    "status",
                ]
            ),
        ), patch.object(invoices.frappe, "get_all", return_value=[invoice_row]), patch.object(
            invoices, "can_read_document", side_effect=can_read
        ):
            summary = invoices.get_invoice_summary([{"doctype": "Customer", "name": "CUST-1"}])

        self.assertEqual(summary["unpaid"], [])
        self.assertEqual(summary["recent"], [])
        self.assertEqual(summary["unpaid_count"], 0)
        self.assertEqual(summary["total_outstanding"], 0)

    def test_appointments_filter_unauthorized_patient_appointments(self):
        appointment_row = frappe._dict(
            {
                "name": "APT-UNAUTHORIZED",
                "patient": "PAT-1",
                "patient_name": "Hidden Patient",
                "status": "Open",
                "appointment_datetime": now_datetime(),
            }
        )

        with patch.object(
            appointments, "get_related_patients_and_customers", return_value=({"PAT-1"}, set())
        ), patch.object(appointments.frappe.db, "exists", return_value=True), patch.object(
            appointments.frappe,
            "get_meta",
            return_value=FakeMeta(["patient", "patient_name", "status", "appointment_datetime"]),
        ), patch.object(appointments.frappe, "get_all", return_value=[appointment_row]), patch.object(
            appointments, "can_read_document", return_value=False
        ):
            result = appointments.get_appointments([{"doctype": "Patient", "name": "PAT-1"}])

        self.assertEqual(result, {"upcoming": [], "recent": []})
