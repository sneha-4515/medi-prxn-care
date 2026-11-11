"""Thin PayPal REST client (Sandbox only): Orders v2 create/capture/get, capture refunds and webhook signature verification.

The client secret is read from the environment and used only here, on the server. Every state-changing call carries a
PayPal-Request-Id so a retry after a network error cannot create or capture twice. Only the Sandbox host is supported on
purpose: this build must never move real money."""
import base64, time, logging
import httpx
from . import config

log = logging.getLogger("mediprxn.paypal")
BASE = "https://api-m.sandbox.paypal.com"
_tok = {"value": None, "exp": 0.0}


class PayPalError(Exception):
    def __init__(self, status, name="", message="", issue=""):
        super().__init__(f"PayPal {status} {name}: {message}")
        self.status, self.name, self.message, self.issue = status, name, message, issue


def configured():
    return bool(config.PAYPAL_CLIENT_ID and config.PAYPAL_CLIENT_SECRET)


def _token():
    if _tok["value"] and _tok["exp"] > time.time() + 30:
        return _tok["value"]
    basic = base64.b64encode(f"{config.PAYPAL_CLIENT_ID}:{config.PAYPAL_CLIENT_SECRET}".encode()).decode()
    r = httpx.post(f"{BASE}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                   headers={"Authorization": f"Basic {basic}"}, timeout=20)
    if r.status_code != 200:
        raise PayPalError(r.status_code, "AUTH", "Could not authenticate with PayPal Sandbox")
    d = r.json(); _tok.update(value=d["access_token"], exp=time.time() + int(d.get("expires_in", 300)))
    return _tok["value"]


def _request(method, path, body=None, request_id=None):
    """Single choke point for HTTP so tests can replace it."""
    if not configured():
        raise PayPalError(503, "NOT_CONFIGURED", "PayPal is not configured on the server")
    h = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json", "Prefer": "return=representation"}
    if request_id: h["PayPal-Request-Id"] = request_id
    r = httpx.request(method, BASE + path, json=body, headers=h, timeout=25)
    try: data = r.json() if r.content else {}
    except ValueError: data = {}
    if r.status_code >= 400:
        details = (data.get("details") or [{}])[0]
        raise PayPalError(r.status_code, data.get("name", ""), data.get("message", ""), details.get("issue", ""))
    return data


def create_order(ref, value, currency, description, request_id):
    """Create a CAPTURE order. `value` is computed on the server from the database, never taken from the browser."""
    body = {"intent": "CAPTURE", "purchase_units": [{
        "reference_id": ref, "custom_id": ref, "invoice_id": ref, "description": description[:127],
        "amount": {"currency_code": currency, "value": value}}]}
    return _request("POST", "/v2/checkout/orders", body, request_id)


def capture_order(order_id, request_id):
    return _request("POST", f"/v2/checkout/orders/{order_id}/capture", {}, request_id)


def get_order(order_id):
    return _request("GET", f"/v2/checkout/orders/{order_id}")


def refund_capture(capture_id, request_id, note="Consultation cancelled"):
    return _request("POST", f"/v2/payments/captures/{capture_id}/refund", {"note_to_payer": note[:255]}, request_id)


def verify_webhook(headers, event):
    """Ask PayPal to verify the webhook signature. Returns True only on SUCCESS; never raises on a bad signature."""
    if not config.PAYPAL_WEBHOOK_ID:
        return False
    h = {k.lower(): v for k, v in headers.items()}
    body = {"auth_algo": h.get("paypal-auth-algo"), "cert_url": h.get("paypal-cert-url"),
            "transmission_id": h.get("paypal-transmission-id"), "transmission_sig": h.get("paypal-transmission-sig"),
            "transmission_time": h.get("paypal-transmission-time"), "webhook_id": config.PAYPAL_WEBHOOK_ID, "webhook_event": event}
    if not all(body[k] for k in ("auth_algo", "cert_url", "transmission_id", "transmission_sig", "transmission_time")):
        return False
    try:
        return _request("POST", "/v1/notifications/verify-webhook-signature", body).get("verification_status") == "SUCCESS"
    except PayPalError:
        log.warning("webhook verification call failed")
        return False
