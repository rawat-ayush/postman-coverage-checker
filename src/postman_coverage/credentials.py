"""Store/retrieve the tool's credentials in the OS keyring.

Uses Windows Credential Manager on Windows, macOS Keychain on macOS, and
Secret Service (or a fallback) on Linux via the `keyring` package. All
public functions swallow keyring failures and return `None` / `False` so
that a broken or missing backend can't crash the GUI.
"""
from __future__ import annotations

from typing import Iterable

_SERVICE = "postman-coverage-checker"

# Stable keyring entry names. Changing these breaks previously-stored values.
KEY_GITHUB_TOKEN = "github_token"
KEY_POSTMAN_API_KEY = "postman_api_key"
KEY_POSTMAN_WORKSPACE_ID = "postman_workspace_id"

ALL_KEYS: tuple[str, ...] = (
    KEY_GITHUB_TOKEN,
    KEY_POSTMAN_API_KEY,
    KEY_POSTMAN_WORKSPACE_ID,
)


def _kr():
    try:
        import keyring

        return keyring
    except Exception:  # noqa: BLE001
        return None


def is_available() -> bool:
    kr = _kr()
    if kr is None:
        return False
    try:
        # A no-op read to verify the backend actually works.
        kr.get_password(_SERVICE, "__probe__")
        return True
    except Exception:  # noqa: BLE001
        return False


def get(key: str) -> str | None:
    kr = _kr()
    if kr is None:
        return None
    try:
        return kr.get_password(_SERVICE, key)
    except Exception:  # noqa: BLE001
        return None


def set_many(values: dict[str, str | None]) -> bool:
    """Save any provided values, delete keys whose value is empty/None.

    Returns True on best-effort success, False if keyring is unusable.
    """
    kr = _kr()
    if kr is None:
        return False
    ok = True
    for key, val in values.items():
        try:
            if val:
                kr.set_password(_SERVICE, key, val)
            else:
                try:
                    kr.delete_password(_SERVICE, key)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            ok = False
    return ok


def clear(keys: Iterable[str] = ALL_KEYS) -> bool:
    kr = _kr()
    if kr is None:
        return False
    ok = True
    for key in keys:
        try:
            kr.delete_password(_SERVICE, key)
        except Exception:  # noqa: BLE001
            # Missing entry is fine, other errors we ignore too.
            pass
    return ok
