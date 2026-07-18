"""Tests for encrypted transaction persistence."""

from __future__ import annotations

from unittest.mock import MagicMock

from cryptography.exceptions import InvalidTag

from custom_components.open_banking.coordinator.transaction_store import OpenBankingTransactionStore


def _store(secret: str = "secret") -> OpenBankingTransactionStore:
    store = OpenBankingTransactionStore(MagicMock(), "entry", secret)
    store._data = {"salt": "MDEyMzQ1Njc4OWFiY2RlZg==", "entries": {}}  # noqa: SLF001
    return store


def test_encryption_round_trip_is_opaque_and_uses_fresh_nonces() -> None:
    """Encrypted blobs restore exactly without exposing serialized data."""
    store = _store()
    cache = {"account": {"booked": [{"description": "Private purchase"}], "pending": []}}

    first = store._encrypt("bank", cache)  # noqa: SLF001
    second = store._encrypt("bank", cache)  # noqa: SLF001

    assert first["nonce"] != second["nonce"]
    assert "Private purchase" not in str(first)
    assert store._decrypt("bank", first) == cache  # noqa: SLF001


def test_tampering_and_credential_rotation_fail_authentication() -> None:
    """AES-GCM rejects modified blobs and keys derived from new credentials."""
    store = _store()
    blob = store._encrypt("bank", {"account": {}})  # noqa: SLF001
    tampered = dict(blob)
    ciphertext = str(tampered["ciphertext"])
    tampered["ciphertext"] = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]

    try:
        store._decrypt("bank", tampered)  # noqa: SLF001
    except InvalidTag:
        pass
    else:
        raise AssertionError("Tampered ciphertext was accepted")

    rotated = _store("new-secret")
    try:
        rotated._decrypt("bank", blob)  # noqa: SLF001
    except InvalidTag:
        pass
    else:
        raise AssertionError("Ciphertext was accepted after credential rotation")
