# /opt/determa/app/github_webhook.py

import hmac
import hashlib
from typing import Optional


def extract_sig_hex(signature_header: Optional[str]) -> Optional[str]:
    """
    Accepts:
      - "sha256=<hex>" (GitHub standard for X-Hub-Signature-256)
      - "sha256:<hex>" (tolerant)
      - "<hex>"        (tolerant fallback)
    Returns hex string or None.
    """
    if not signature_header:
        return None

    s = signature_header.strip()
    if not s:
        return None

    if s.startswith("sha256="):
        return s.split("=", 1)[1].strip() or None
    if s.startswith("sha256:"):
        return s.split(":", 1)[1].strip() or None

    # fallback, accept raw hex
    return s


def verify_github_signature_256(*, secret: str, body: bytes, signature_header: Optional[str]) -> bool:
    """
    Verifies GitHub HMAC SHA256 signature.

    GitHub sends header:
      X-Hub-Signature-256: sha256=<hexdigest>
    """
    if not secret:
        return False
    if body is None:
        return False

    their_hex = extract_sig_hex(signature_header)
    if not their_hex:
        return False

    mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, their_hex)