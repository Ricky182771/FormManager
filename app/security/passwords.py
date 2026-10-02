from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi defaults to Argon2id with RFC 9106 "low memory" parameters.
_hasher = PasswordHasher()

# Verified when the username is wrong so both failure paths cost the same time.
_DUMMY_HASH = _hasher.hash("timing-equalizer-not-a-real-password")


def hash_secret(plaintext: str) -> str:
    if not plaintext:
        raise ValueError("the value must not be empty")
    return _hasher.hash(plaintext)


def verify_secret(stored_hash: str | None, plaintext: str) -> bool:
    target = stored_hash or _DUMMY_HASH
    try:
        ok = _hasher.verify(target, plaintext)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return ok and stored_hash is not None
