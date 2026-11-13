"""Google Wallet: the "Save to Google Wallet" link of a card (contract, section 13.6).

The link is `https://pay.google.com/gp/v/save/<jwt>`. The JWT is signed (RS256)
with the key of the issuer's service account and carries both the business's
`LoyaltyClass` and the customer's `LoyaltyObject`: Google creates them the first
time the card is saved, so no API call is needed here.

- Class id `<issuer>.business_<business_id>`, object id `<issuer>.customer_<customer_id>`.
- The barcode is a QR whose value is exactly the card `code`: the checkout reads it.
- The pass is a snapshot (DECISIÓN 13): once saved, Google keeps the object it
  already has; tier or name changes are not pushed.
- Not configured (any of issuer, service account or logo missing) means
  `is_configured()` is false: the card page hides the button and the endpoint
  answers 503.
"""

import json
from datetime import datetime
from typing import Any

import jwt

from core.config import settings
from models.business_model import Business
from models.customer_model import Customer
from models.tier_model import Tier

SAVE_URL = "https://pay.google.com/gp/v/save/"
ISSUER_NAME = "Member+"


def _service_account() -> dict[str, str] | None:
    try:
        account = json.loads(settings.google_wallet_service_account_json)
    except ValueError:
        return None
    if not isinstance(account, dict):
        return None
    if not account.get("client_email") or not account.get("private_key"):
        return None
    return account


def is_configured() -> bool:
    return bool(
        settings.google_wallet_issuer_id
        and settings.google_wallet_logo_url
        and _service_account() is not None
    )


def _logo(business: Business) -> str:
    if business.logo_url and business.logo_url.startswith("https://"):
        return business.logo_url
    return settings.google_wallet_logo_url


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def loyalty_class(business: Business) -> dict[str, Any]:
    return {
        "id": f"{settings.google_wallet_issuer_id}.business_{business.id}",
        "issuerName": ISSUER_NAME,
        "programName": business.name,
        "programLogo": {"sourceUri": {"uri": _logo(business)}},
        "reviewStatus": "UNDER_REVIEW",
    }


def loyalty_object(
    business: Business, customer: Customer, tier: Tier, valid_until: datetime
) -> dict[str, Any]:
    issuer = settings.google_wallet_issuer_id
    return {
        "id": f"{issuer}.customer_{customer.id}",
        "classId": f"{issuer}.business_{business.id}",
        "state": "ACTIVE",
        "accountName": customer.full_name,
        "accountId": customer.code,
        "barcode": {"type": "QR_CODE", "value": customer.code, "alternateText": customer.code},
        "textModulesData": [{"id": "tier", "header": "Nivel", "body": tier.name}],
        "validTimeInterval": {"end": {"date": _iso(valid_until)}},
    }


def save_url(
    business: Business, customer: Customer, tier: Tier, valid_until: datetime, now: datetime
) -> str:
    """Signed "Save to Google Wallet" link. Call only when `is_configured()`."""
    account = _service_account()
    if account is None:  # pragma: no cover - guarded by is_configured()
        raise RuntimeError("Google Wallet is not configured")
    claims = {
        "iss": account["client_email"],
        "aud": "google",
        "typ": "savetowallet",
        "iat": int(now.timestamp()),
        "origins": settings.google_wallet_origins,
        "payload": {
            "loyaltyClasses": [loyalty_class(business)],
            "loyaltyObjects": [loyalty_object(business, customer, tier, valid_until)],
        },
    }
    token = jwt.encode(claims, account["private_key"], algorithm="RS256")
    return SAVE_URL + token
