"""Composition helper for optional operational history backends."""

from __future__ import annotations

from semapact.history.operational import OperationalHistorySink


def create_operational_history_sink(
    uri: str | None,
) -> OperationalHistorySink | None:
    """Create a configured operational sink, or disable persistence when omitted."""
    if uri is None or not uri.strip():
        return None
    cleaned = uri.strip()

    if cleaned.startswith("sqlite:///"):
        from semapact.platforms.sqlite import SQLiteOperationalHistorySink

        path = cleaned.removeprefix("sqlite:///")
        if not path:
            raise ValueError("SQLite operational history URI requires a path")
        return SQLiteOperationalHistorySink(path)

    if cleaned.startswith("delta:///"):
        from semapact.platforms.delta import DeltaOperationalHistorySink

        table_uri = cleaned.removeprefix("delta:///")
        if not table_uri:
            raise ValueError("Delta operational history URI requires a table path")
        return DeltaOperationalHistorySink(table_uri)

    raise ValueError(
        "Unsupported operational history URI. Use sqlite:///... or delta:///..."
    )
