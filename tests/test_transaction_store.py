"""Tests for encrypted transaction persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.exceptions import InvalidTag

from custom_components.open_banking.const import (
    CONF_TRANSACTION_STORAGE,
    TRANSACTION_STORAGE_ENCRYPTED,
    TRANSACTION_STORAGE_MEMORY,
)
from custom_components.open_banking.coordinator import OpenBankingDataUpdateCoordinator
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


async def test_store_async_save_restore_and_delete_uses_only_ciphertext(hass) -> None:
    """The Home Assistant storage wrapper persists opaque data and restores it."""
    persisted: dict | None = None

    class FakeStore:
        @classmethod
        def __class_getitem__(cls, item: object) -> type[FakeStore]:
            return cls

        def __init__(self, *args: object) -> None:
            pass

        async def async_load(self) -> dict | None:
            return None

        async def async_save(self, data: dict) -> None:
            nonlocal persisted
            persisted = data.copy()

    with patch("custom_components.open_banking.coordinator.transaction_store.Store", FakeStore):
        store = OpenBankingTransactionStore(hass, "entry", "secret")
        await store.async_initialize()
        await store.async_save("bank", {"account": {"booked": [{"description": "Private"}]}})

        assert persisted is not None
        assert "Private" not in str(persisted)
        assert await store.async_load("bank") == {"account": {"booked": [{"description": "Private"}]}}

        await store.async_delete("bank")
        assert persisted["entries"] == {}


async def test_coordinator_restores_encrypted_cache_and_deletes_it_for_memory(hass) -> None:
    """Storage mode transitions restore encrypted data or remove persisted data."""
    transaction_store = MagicMock()
    transaction_store.async_load = AsyncMock(return_value={"account": {"booked": [], "pending": []}})
    transaction_store.async_delete = AsyncMock()
    subentry = MagicMock(subentry_id="bank")
    subentry.data = {CONF_TRANSACTION_STORAGE: TRANSACTION_STORAGE_ENCRYPTED}
    coordinator = OpenBankingDataUpdateCoordinator(
        hass,
        MagicMock(),
        subentry,
        MagicMock(),
        transaction_store=transaction_store,
    )

    await coordinator.async_restore_transactions()
    assert coordinator.transactions == {"account": {"booked": [], "pending": []}}
    transaction_store.async_load.assert_awaited_once_with("bank")

    subentry.data = {CONF_TRANSACTION_STORAGE: TRANSACTION_STORAGE_MEMORY}
    await coordinator.async_restore_transactions()
    transaction_store.async_delete.assert_awaited_once_with("bank")


async def test_public_load_discards_tampered_ciphertext(hass) -> None:
    """Authentication failure through public loading deletes the unreadable cache."""
    store = OpenBankingTransactionStore(hass, "entry", "secret")
    store._data = {"salt": "MDEyMzQ1Njc4OWFiY2RlZg==", "entries": {}}  # noqa: SLF001
    blob = store._encrypt("bank", {"account": {}})  # noqa: SLF001
    ciphertext = str(blob["ciphertext"])
    blob["ciphertext"] = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]
    store._data["entries"]["bank"] = blob  # noqa: SLF001
    store._store.async_save = AsyncMock()  # noqa: SLF001

    assert await store.async_load("bank") == {}
    assert store._data["entries"] == {}  # noqa: SLF001
    store._store.async_save.assert_awaited_once()  # noqa: SLF001
