"""Private canonical-JSON and SHA-256 helpers for stable identities.

Reused by later phases (artifact hashing in Phase 3+, manifest digests in
storage). Canonical JSON here means: UTF-8 bytes, sorted keys, compact
separators ``(",", ":")``, non-ASCII emitted as-is, and ``NaN``/``Infinity``
refused (``allow_nan=False``). ``stable_id`` wraps a canonical digest in the
opaque ``sha256:<64 lower-case hex>`` form used by every identity model.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize ``payload`` to canonical JSON as UTF-8 bytes.

    Args:
        payload: any JSON-serializable value; non-finite floats are refused.

    Returns:
        Canonical JSON encoded as UTF-8.
    """
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return text.encode("utf-8")


def canonical_json(payload: Any) -> str:
    """Return the canonical JSON text (UTF-8 decoded) for ``payload``."""
    return canonical_json_bytes(payload).decode("utf-8")


def sha256_hex(data: bytes | bytearray | memoryview) -> str:
    """Return the lower-case hex SHA-256 of raw ``data``.

    Operates on a bytes buffer so callers can hash files or arrays in chunks
    instead of materializing a full ``.tobytes()`` copy.
    """
    return hashlib.sha256(data).hexdigest()


def sha256_digest(payload: Any) -> str:
    """Return the lower-case hex SHA-256 of ``payload``'s canonical JSON."""
    return sha256_hex(canonical_json_bytes(payload))


def stable_id(payload: Any) -> str:
    """Return an opaque ``sha256:<hex>`` id derived from ``payload``.

    The id is path/object-address independent: identical canonical JSON always
    yields the same string.
    """
    return f"sha256:{sha256_digest(payload)}"
