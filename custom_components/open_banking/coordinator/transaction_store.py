"""Encrypted persistent transaction cache storage."""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from custom_components.open_banking.const import DOMAIN, TRANSACTION_CACHE_FORMAT_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .transactions import TransactionCache


class OpenBankingTransactionStore:
    """Store independently encrypted transaction caches by subentry."""

    def __init__(self, hass: HomeAssistant, entry_id: str, secret_key: str) -> None:
        """Initialize encrypted transaction storage."""
        self._hass = hass
        self._entry_id = entry_id
        self._secret_key = secret_key
        self._store = Store[dict[str, Any]](
            hass,
            TRANSACTION_CACHE_FORMAT_VERSION,
            f"{DOMAIN}.transactions.{entry_id}",
        )
        self._data: dict[str, Any] = {}

    async def async_initialize(self) -> None:
        """Load encrypted cache metadata."""
        loaded = await self._store.async_load()
        if (
            not isinstance(loaded, dict)
            or not isinstance(loaded.get("salt"), str)
            or not isinstance(loaded.get("entries"), dict)
        ):
            self._data = {"salt": _encode(os.urandom(16)), "entries": {}}
            return
        try:
            _decode(loaded["salt"])
        except ValueError, TypeError:
            self._data = {"salt": _encode(os.urandom(16)), "entries": {}}
            return
        self._data = loaded

    async def async_load(self, subentry_id: str) -> TransactionCache:
        """Decrypt one subentry cache, discarding unreadable data."""
        blob = self._data.get("entries", {}).get(subentry_id)
        if not isinstance(blob, dict):
            return {}
        try:
            return await self._hass.async_add_executor_job(self._decrypt, subentry_id, blob)
        except InvalidTag, ValueError, KeyError, TypeError:
            await self.async_delete(subentry_id)
            return {}

    async def async_save(self, subentry_id: str, cache: TransactionCache) -> None:
        """Encrypt and persist one subentry cache."""
        blob = await self._hass.async_add_executor_job(self._encrypt, subentry_id, cache)
        self._data.setdefault("entries", {})[subentry_id] = blob
        await self._store.async_save(self._data)

    async def async_delete(self, subentry_id: str) -> None:
        """Delete one persisted cache."""
        entries = self._data.setdefault("entries", {})
        if entries.pop(subentry_id, None) is not None:
            await self._store.async_save(self._data)

    async def async_prune(self, active_subentry_ids: set[str]) -> None:
        """Remove caches for deleted bank connections."""
        entries = self._data.setdefault("entries", {})
        changed = False
        for subentry_id in set(entries) - active_subentry_ids:
            entries.pop(subentry_id)
            changed = True
        if changed:
            await self._store.async_save(self._data)

    def _encrypt(self, subentry_id: str, cache: TransactionCache) -> dict[str, str | int]:
        nonce = os.urandom(12)
        plaintext = json.dumps(cache, separators=(",", ":"), ensure_ascii=False).encode()
        ciphertext = AESGCM(self._key()).encrypt(nonce, plaintext, self._aad(subentry_id))
        return {"version": TRANSACTION_CACHE_FORMAT_VERSION, "nonce": _encode(nonce), "ciphertext": _encode(ciphertext)}

    def _decrypt(self, subentry_id: str, blob: dict[str, Any]) -> TransactionCache:
        if blob.get("version") != TRANSACTION_CACHE_FORMAT_VERSION:
            raise ValueError("Unsupported transaction cache version")
        plaintext = AESGCM(self._key()).decrypt(
            _decode(blob["nonce"]),
            _decode(blob["ciphertext"]),
            self._aad(subentry_id),
        )
        value = json.loads(plaintext)
        if not isinstance(value, dict):
            raise TypeError("Transaction cache was not an object")
        return value

    def _key(self) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_decode(self._data["salt"]),
            info=f"{DOMAIN}.transactions.v{TRANSACTION_CACHE_FORMAT_VERSION}:{self._entry_id}".encode(),
        ).derive(self._secret_key.encode())

    def _aad(self, subentry_id: str) -> bytes:
        return f"{DOMAIN}:{self._entry_id}:{subentry_id}:{TRANSACTION_CACHE_FORMAT_VERSION}".encode()


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode()


def _decode(value: str) -> bytes:
    return base64.b64decode(value, validate=True)
