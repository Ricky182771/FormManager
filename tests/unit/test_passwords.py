from __future__ import annotations

import pytest

from app.security import passwords
from app.security.passwords import hash_secret, verify_secret


def test_argon2id_hash_and_verify() -> None:
    digest = hash_secret("bob-example-secret")
    assert digest.startswith("$argon2id$")
    assert "bob-example-secret" not in digest
    assert verify_secret(digest, "bob-example-secret")


def test_wrong_password_rejected() -> None:
    assert not verify_secret(hash_secret("bob-example-secret"), "carol-example")


def test_invalid_hash_does_not_crash() -> None:
    assert not verify_secret("not-a-hash", "x")
    assert not verify_secret("$argon2id$v=19$m=garbage", "x")


def test_empty_secret_cannot_be_hashed() -> None:
    with pytest.raises(ValueError):
        hash_secret("")


def test_missing_hash_still_runs_argon2(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = passwords._hasher

    class Spy:
        def verify(self, stored: str, plaintext: str) -> bool:
            calls.append(stored)
            return real.verify(stored, plaintext)

    monkeypatch.setattr(passwords, "_hasher", Spy())
    assert not verify_secret(None, "timing-equalizer-not-a-real-password")
    assert calls == [passwords._DUMMY_HASH], "dummy path must cost one real Argon2 verification"
