# Gain Maqsam Integration

Connect ERPNext to the [Maqsam](https://www.maqsam.com/) cloud call-center: inbound popups, click-to-call, recording archive, and a unified Caller 360 across Patient / Customer / Lead / Contact.

## Features

- **Caller 360 drawer** — slides in on every incoming call with a live timer, formatted phone, the matched record (Patient/Customer/Lead/Contact), recent calls, outstanding invoices, upcoming appointments, and one-click actions.
- **Quick-create flow** — for unknown numbers the drawer opens a Patient or Lead quick entry with the mobile pre-filled, and offers to create an appointment immediately after saving a Patient.
- **Click-to-call** — buttons on Lead, Contact, Customer, Patient, and Patient Appointment forms place the call through Maqsam, validate the agent is online, and record everything in a `Maqsam Call Log`.
- **Webhook + sync** — production ingest is the webhook; a 5-minute scheduler tops it up if a delivery is ever missed.
- **Recording archive** — fetches the MP3 from Maqsam on demand, stores it as a private File, and serves it back from the call log.
- **Maqsam Autologin** — opens the Maqsam portal with the current Frappe user’s session.

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/abdelrahimhaseeb/gain_maqsam_integration --branch main
bench --site <your-site> install-app gain_maqsam_integration
bench build --app gain_maqsam_integration
```

`erpnext` is required. Healthcare features (Patient, Patient Appointment) activate automatically when the `healthcare` app is installed.

## Configuration

Open **Maqsam Settings** (System Manager only):

| Field | Notes |
|---|---|
| Enable Maqsam Integration | Master switch |
| Base URL | `maqsam.com` (the host without `api.` / `portal.`) |
| Access Key ID / Access Secret | From Maqsam dashboard → Developers → API |
| Default Caller Number | Used as the outbound caller-id when not specified |
| Default Agent Email | Fallback when the webhook payload omits `agentEmail` |
| Timeout Seconds | HTTP timeout for Maqsam API calls (default 30) |
| Enable Incoming Call Popup | Toggles the realtime drawer |
| Incoming Webhook URL | Auto-filled on save — copy this into Maqsam |
| Incoming Webhook Token | Shared secret; presented as `X-Maqsam-Webhook-Token` |

### Wiring the webhook in Maqsam

In Maqsam Portal → **Developers → Webhooks**:

- **URL:** value of `Incoming Webhook URL` (e.g. `https://your-site.example.com/api/method/gain_maqsam_integration.api.maqsam_receive_call_event`)
- **Method:** `POST`
- **Header:** `X-Maqsam-Webhook-Token: <your token>`
- **Events:** Inbound call ringing / in-progress / ended (whichever Maqsam exposes)

The endpoint accepts the standard Maqsam payload shape and several aliases (`caller`/`callerNumber`/`from`, `state`/`status`, `agents[]`/`agentEmail`, etc.). Unknown fields are stored verbatim in `raw_payload`.

### Roles

The patch creates a **Maqsam Agent** role on install. Assign it to call-center staff — they get write access to `Maqsam Call Log` and receive the incoming-call popup. Other Desk Users only see the logs (read-only). System Managers retain full access.

If no specific agent is resolved from the payload (and no `Default Agent Email` is set), the popup is broadcast to every user holding the Maqsam Agent role.

## Architecture

```
Maqsam Portal ──webhook──► /api/method/...maqsam_receive_call_event
                              │
                              ├─ rate_limit(120/min) + token check
                              ├─ upsert_maqsam_call (UNIQUE on maqsam_call_id)
                              └─ enqueue dispatch ──► get_caller_profile
                                                    └─ publish_realtime("maqsam_incoming_call")
                                                              │
                                  Frappe Desk (browser) ◄─── socket.io
                                                              │
                                                  Caller 360 drawer
```

Hot path returns within a few hundred milliseconds; the heavy `find_matches`/`get_caller_profile` work happens on the `short` queue.

## Maintenance

| Job | Schedule | Purpose |
|---|---|---|
| `maqsam_auto_sync_recent_calls` | every 5 minutes | Backfill any webhook deliveries that were missed |
| `maqsam_trim_old_payloads` | daily | Clears `raw_payload` JSON on call logs older than 90 days |
| `maqsam_cleanup_old_recordings` | daily | Deletes recording File attachments older than 90 days |

Adjust retention by passing `days=...` if you call them manually, e.g.:

```bash
bench --site <your-site> execute gain_maqsam_integration.api.maqsam_trim_old_payloads --kwargs '{"days": 180}'
```

## Tests

```bash
bench --site <your-site> set-config allow_tests true
bench --site <your-site> run-tests --app gain_maqsam_integration
```

Coverage includes timestamp parsing, outcome inference, call-id extraction, upsert idempotency under duplicate ids, phone matching helpers, webhook payload aliasing, agent extraction, and the auth/queue contract of the webhook endpoint.

## Troubleshooting

**The drawer doesn’t appear when an inbound call rings.**
1. Confirm `Enable Incoming Call Popup` is on.
2. Check the receiving user holds the `Maqsam Agent` role (or that `Default Agent Email` resolves to them).
3. In the browser DevTools console: `frappe.realtime.socket.hasListeners('maqsam_incoming_call')` should return `true`. If `false`, hard-reload — the bundled JS uses a content-hashed filename, so a normal refresh after `bench build` is enough.

**Webhook returns `Invalid Maqsam webhook token`.**
The token in the request header doesn’t match the `Incoming Webhook Token` setting. The comparison is constant-time (`hmac.compare_digest`).

**Two duplicate logs for the same `maqsam_call_id`.**
Should not happen — `maqsam_call_id` is `UNIQUE` and `upsert_maqsam_call` retries on `UniqueValidationError`. If you see duplicates, run the dedupe patch:

```bash
bench --site <your-site> execute gain_maqsam_integration.patches.dedupe_maqsam_call_id.execute
```

**Recordings won’t play.**
The recording is fetched on demand from Maqsam the first time it’s opened, then cached as a private File. Recordings older than 90 days are removed by the cleanup job — adjust the cron in `hooks.py` if you need longer retention.

## License

MIT — see `license.txt`.
