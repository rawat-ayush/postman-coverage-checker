"""Postman Coverage Checker package."""

__version__ = "0.1.0"

# Use the OS trust store for HTTPS when available. This lets the tool work
# behind corporate MITM proxies whose CA isn't in `certifi`. Silently no-ops
# if `truststore` isn't installed.
try:  # pragma: no cover
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass
