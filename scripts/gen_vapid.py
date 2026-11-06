"""通知の鍵（VAPID）を作って標準出力に出す。ファイルには書かない。

    .venv/bin/python scripts/gen_vapid.py

出た3行を `.env` に書く（コミットしない）。`TSUTAE_VAPID_SUBJECT` は自分の連絡先に直す。
鍵を作り直すと、登録済みの端末は通知をオンにし直すまで届かなくなる。
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_vapid_keys() -> tuple[str, str]:
    """(公開鍵, 秘密鍵)。公開鍵は 65 バイトの点、秘密鍵は 32 バイトの値の base64url。"""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint
    )
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return _b64url(public), _b64url(private)


def main() -> int:
    public, private = generate_vapid_keys()
    print(f"TSUTAE_VAPID_PUBLIC_KEY={public}")
    print(f"TSUTAE_VAPID_PRIVATE_KEY={private}")
    print("TSUTAE_VAPID_SUBJECT=mailto:you@example.com")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
