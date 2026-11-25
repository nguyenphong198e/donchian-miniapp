"""Encrypt the mini app data so the public GitHub page shows nothing without the owner's password.

    python engine/seal.py            # docs/data/dashboard.json (paper) + private/live.json (real) -> docs/data/vault.json

Password: private/password.txt (never committed). Key = PBKDF2-HMAC-SHA256(password, random salt, ITER), cipher =
AES-256-GCM with a random 12-byte IV; the page decrypts with WebCrypto using the same parameters.
"""
import base64
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parents[1]
PRIV = ROOT / "private"
ITER = 310_000
b64 = lambda b: base64.b64encode(b).decode()


def main() -> int:
    pw = (PRIV / "password.txt").read_text(encoding="utf-8").strip()
    if len(pw) < 12:
        print("password.txt too short", file=sys.stderr)
        return 1
    paper = json.loads((ROOT / "docs" / "data" / "dashboard.json").read_text(encoding="utf-8"))
    lp = PRIV / "live.json"
    live = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() and lp.stat().st_size else None
    plain = json.dumps({"paper": paper, "live": live}, ensure_ascii=False, separators=(",", ":")).encode()
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode())
    ct = AESGCM(key).encrypt(iv, plain, None)
    vault = {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct),
             "updated": paper.get("meta", {}).get("updated")}
    (ROOT / "docs" / "data" / "vault.json").write_text(json.dumps(vault), encoding="utf-8")
    print(f"[seal] vault.json {len(ct):,} bytes (paper + {'live' if live else 'no live'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
