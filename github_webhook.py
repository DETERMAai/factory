import hmac
import hashlib
from typing import Optional, Any


IGNORED_SENDERS = {
    "github-actions[bot]",
    "dependabot[bot]",
    "determa-bot",
}

IGNORED_REF_PREFIXES = (
    "refs/heads/determa/",
    "refs/heads/factory-",
    "refs/heads/revert-",
)

ALLOWED_EVENTS = {
    "push",
}


def extract_sig_hex(signature_header: Optional[str]) -> Optional[str]:
    if not signature_header:
        return None

    s = signature_header.strip()
    if not s:
        return None

    if s.startswith("sha256="):
        return s.split("=", 1)[1].strip() or None
    if s.startswith("sha256:"):
        return s.split(":", 1)[1].strip() or None

    return s


def verify_github_signature_256(*, secret: str, body: bytes, signature_header: Optional[str]) -> bool:
    if not secret:
        return False
    if body is None:
        return False

    their_hex = extract_sig_hex(signature_header)
    if not their_hex:
        return False

    mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, their_hex)


def get_sender_login(payload: dict[str, Any]) -> str:
    sender = payload.get("sender") or {}
    return str(sender.get("login") or "").strip()


def get_ref(payload: dict[str, Any]) -> str:
    return str(payload.get("ref") or "").strip()


def should_ignore_sender(payload: dict[str, Any]) -> bool:
    login = get_sender_login(payload)
    return login in IGNORED_SENDERS


def should_ignore_ref(payload: dict[str, Any]) -> bool:
    ref = get_ref(payload)
    return any(ref.startswith(prefix) for prefix in IGNORED_REF_PREFIXES)


def should_process_event(event_name: Optional[str], payload: dict[str, Any]) -> bool:
    if not event_name:
        return False

    if event_name not in ALLOWED_EVENTS:
        return False

    if should_ignore_sender(payload):
        return False

    if should_ignore_ref(payload):
        return False

    return True


def extract_delivery_id(headers: dict[str, Any]) -> str:
    value = headers.get("X-GitHub-Delivery") or headers.get("x-github-delivery") or ""
    return str(value).strip()
