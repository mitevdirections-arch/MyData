from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
import uuid


def _b64url_decode(data: str) -> bytes:
    raw = str(data or "").strip()
    pad = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode((raw + pad).encode("ascii"))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_headers(
    *,
    method: str,
    path: str,
    body_bytes: bytes,
    bot_id: str,
    key_version: int,
    signing_secret_b64url: str,
) -> dict[str, str]:
    ts = int(time.time())
    nonce = uuid.uuid4().hex
    body_sha = hashlib.sha256(body_bytes).hexdigest()
    canonical = f"{method.upper()}\n{path}\n{ts}\n{nonce}\n{body_sha}".encode("utf-8")
    key = _b64url_decode(signing_secret_b64url)
    sig = _b64url_encode(hmac.new(key, canonical, hashlib.sha256).digest())
    return {
        "X-Bot-ID": str(bot_id),
        "X-Bot-Key-Version": str(int(key_version)),
        "X-Bot-Timestamp": str(ts),
        "X-Bot-Nonce": nonce,
        "X-Bot-Signature": sig,
    }


def _request_json(
    method: str,
    url: str,
    path: str,
    token: str,
    payload: dict,
    *,
    bot_id: str | None,
    bot_key_version: int | None,
    bot_signing_secret: str | None,
) -> dict:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")

    if bot_id and bot_key_version is not None and bot_signing_secret:
        signed = _sign_headers(
            method=method,
            path=path,
            body_bytes=body,
            bot_id=bot_id,
            key_version=bot_key_version,
            signing_secret_b64url=bot_signing_secret,
        )
        for k, v in signed.items():
            req.add_header(k, v)

    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Tenant guard agent (signed heartbeat + license snapshot)")
    p.add_argument("--api-base", required=True, help="API base URL")
    p.add_argument("--token", required=True, help="Bearer token for tenant user")
    p.add_argument("--device-id", required=True, help="Stable device identifier")
    p.add_argument("--status", default="OK", help="Heartbeat status")
    p.add_argument("--event", default="KEEPALIVE", help="STARTUP / KEEPALIVE / LOGOUT")

    p.add_argument("--bot-id", default=None, help="Guard bot credential id")
    p.add_argument("--bot-key-version", type=int, default=None, help="Guard bot key version")
    p.add_argument("--bot-signing-secret", default=None, help="Guard bot signing secret (base64url)")

    p.add_argument("--send-heartbeat", action="store_true", help="Send /guard/heartbeat")
    p.add_argument("--send-license-snapshot", action="store_true", help="Send /guard/license-snapshot")
    p.add_argument("--active-license-code", action="append", default=[], help="Repeatable active license visual code")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    base = str(args.api_base).rstrip("/")
    token = str(args.token).strip()
    device_id = str(args.device_id).strip()

    bot_id = str(args.bot_id).strip() if args.bot_id else None
    bot_key_version = int(args.bot_key_version) if args.bot_key_version is not None else None
    bot_signing_secret = str(args.bot_signing_secret).strip() if args.bot_signing_secret else None

    try:
        if args.send_heartbeat:
            path = "/guard/heartbeat"
            hb = _request_json(
                "POST",
                f"{base}{path}",
                path,
                token,
                {
                    "device_id": device_id,
                    "status": str(args.status).strip().upper(),
                    "event": str(args.event).strip().upper(),
                },
                bot_id=bot_id,
                bot_key_version=bot_key_version,
                bot_signing_secret=bot_signing_secret,
            )
            print(json.dumps({"heartbeat": hb}, ensure_ascii=False))

        if args.send_license_snapshot:
            path = "/guard/license-snapshot"
            codes = [str(x).strip().upper() for x in list(args.active_license_code or []) if str(x).strip()]
            snap = _request_json(
                "POST",
                f"{base}{path}",
                path,
                token,
                {
                    "device_id": device_id,
                    "active_license_codes": codes,
                },
                bot_id=bot_id,
                bot_key_version=bot_key_version,
                bot_signing_secret=bot_signing_secret,
            )
            print(json.dumps({"license_snapshot": snap}, ensure_ascii=False))

        if not args.send_heartbeat and not args.send_license_snapshot:
            print(json.dumps({"ok": False, "detail": "nothing_to_send"}, ensure_ascii=False))
            return 2

        return 0

    except urllib.error.HTTPError as exc:
        detail = None
        body_text = None
        try:
            body_text = exc.read().decode("utf-8", errors="replace")
            parsed = json.loads(body_text)
            detail = parsed.get("detail") if isinstance(parsed, dict) else None
        except Exception:  # noqa: BLE001
            pass

        out = {
            "ok": False,
            "http_status": int(getattr(exc, "code", 0) or 0),
            "detail": detail or body_text or str(exc),
        }
        print(json.dumps(out, ensure_ascii=False))
        return 1
    except urllib.error.URLError as exc:
        print(json.dumps({"ok": False, "detail": f"network_error:{exc.reason}"}, ensure_ascii=False))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "detail": f"agent_error:{exc}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())