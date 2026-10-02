"""Interactive Argon2id hash generator: python -m app.security.generate_hash

The password is read with getpass (no echo, never a shell argument) and only the hash is printed.
"""

from __future__ import annotations

import getpass
import sys

from app.security.passwords import hash_secret

MIN_LENGTH = 12


def main() -> int:
    first = getpass.getpass("Contraseña de administrador (no se mostrará): ")
    if len(first) < MIN_LENGTH:
        print(f"Debe tener al menos {MIN_LENGTH} caracteres.", file=sys.stderr)
        return 1
    second = getpass.getpass("Repite la contraseña: ")
    if first != second:
        print("Las contraseñas no coinciden.", file=sys.stderr)
        return 1
    # Single quotes stop docker compose from interpolating the "$" characters of the hash.
    print(f"ADMIN_PASSWORD_HASH='{hash_secret(first)}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
