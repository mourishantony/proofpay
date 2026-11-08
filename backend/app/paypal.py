"""Minimal PayPal REST client (sandbox): Orders v2, Payments v2, Payouts v1, Webhooks."""
import time
import uuid
from typing import Any, Optional

import httpx

from .config import settings


class PayPalError(Exception):
    def __init__(self, message: str, status: int = 0, details: Any = None):
        super().__init__(message)
        self.status = status
        self.details = details


class PayPalClient:
    def __init__(self, client_id: str, client_secret: str, base_url: str, timeout: float = 30.0):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(timeout=timeout)
        self._token: Optional[str] = None
        self._token_expiry = 0.0

    # ---- auth -----------------------------------------------------------
    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        if not (self.client_id and self.client_secret):
            raise PayPalError("PayPal credentials are not configured (PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET).")
        resp = self._http.post(
            f"{self.base_url}/v1/oauth2/token",
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
        )
        if resp.status_code != 200:
            raise PayPalError("PayPal authentication failed", resp.status_code, _safe_json(resp))
        body = resp.json()
        self._token = body["access_token"]
        self._token_expiry = time.time() + int(body.get("expires_in", 300))
        return self._token

    def _request(self, method: str, path: str, json: Any = None, idempotency_key: Optional[str] = None) -> dict:
        headers = {"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"}
        if method == "POST":
            headers["PayPal-Request-Id"] = idempotency_key or str(uuid.uuid4())
        resp = self._http.request(method, f"{self.base_url}{path}", json=json, headers=headers)
        if resp.status_code >= 400:
            details = _safe_json(resp)
            msg = details.get("message") or details.get("name") or resp.text[:200] if isinstance(details, dict) else resp.text[:200]
            raise PayPalError(f"PayPal {method} {path} failed: {msg}", resp.status_code, details)
        return _safe_json(resp) if resp.content else {}

    # ---- orders / payments ------------------------------------------------
    def create_authorize_order(self, *, reference_id: str, custom_id: str, description: str, amount: str, currency: str) -> dict:
        body = {
            "intent": "AUTHORIZE",
            "purchase_units": [
                {
                    "reference_id": reference_id,
                    "custom_id": custom_id,
                    "description": description[:127],
                    "amount": {"currency_code": currency, "value": amount},
                }
            ],
        }
        return self._request("POST", "/v2/checkout/orders", body)

    def authorize_order(self, order_id: str) -> dict:
        return self._request("POST", f"/v2/checkout/orders/{order_id}/authorize", {})

    def capture_authorization(self, authorization_id: str, idempotency_key: str) -> dict:
        return self._request(
            "POST", f"/v2/payments/authorizations/{authorization_id}/capture", {"final_capture": True}, idempotency_key
        )

    def void_authorization(self, authorization_id: str) -> dict:
        return self._request("POST", f"/v2/payments/authorizations/{authorization_id}/void", None)

    # ---- payouts ------------------------------------------------------------
    def create_payout(self, *, sender_batch_id: str, items: list[dict], currency: str, note: str) -> dict:
        body = {
            "sender_batch_header": {
                "sender_batch_id": sender_batch_id,
                "email_subject": "You received a milestone payout via ProofPay",
                "email_message": note,
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "receiver": it["email"],
                    "amount": {"value": it["amount"], "currency": currency},
                    "note": note,
                    "sender_item_id": it["sender_item_id"],
                }
                for it in items
            ],
        }
        return self._request("POST", "/v1/payments/payouts", body, idempotency_key=sender_batch_id)

    def get_payout(self, payout_batch_id: str) -> dict:
        return self._request("GET", f"/v1/payments/payouts/{payout_batch_id}")

    # ---- webhooks -------------------------------------------------------------
    def verify_webhook(self, headers: dict, event: dict, webhook_id: str) -> bool:
        h = {k.lower(): v for k, v in headers.items()}
        body = {
            "auth_algo": h.get("paypal-auth-algo"),
            "cert_url": h.get("paypal-cert-url"),
            "transmission_id": h.get("paypal-transmission-id"),
            "transmission_sig": h.get("paypal-transmission-sig"),
            "transmission_time": h.get("paypal-transmission-time"),
            "webhook_id": webhook_id,
            "webhook_event": event,
        }
        if not all(body.values()):
            return False
        result = self._request("POST", "/v1/notifications/verify-webhook-signature", body)
        return result.get("verification_status") == "SUCCESS"


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text[:500]}


_client: Optional[PayPalClient] = None


def get_paypal() -> PayPalClient:
    """Singleton accessor; tests replace it via set_paypal()."""
    global _client
    if _client is None:
        _client = PayPalClient(settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_base_url)
    return _client


def set_paypal(client) -> None:
    global _client
    _client = client


def authorization_id_from(order: dict) -> Optional[str]:
    try:
        return order["purchase_units"][0]["payments"]["authorizations"][0]["id"]
    except (KeyError, IndexError, TypeError):
        return None
