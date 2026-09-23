"""Shared connector contract for confirmed financial records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ConnectorResult:
    """Non-sensitive connector outcome returned to the application."""

    name: str
    configured: bool
    connected: bool
    written: bool = False
    readable: bool = False
    status: str = "Not configured"

    def as_status(self) -> str:
        if not self.configured:
            return "Not configured"
        if self.written:
            return "Delivered"
        if self.connected:
            return "Connected"
        return self.status


class Connector(Protocol):
    """Minimal interface that future ERP/database connectors can implement."""

    name: str

    def test_connection(self) -> ConnectorResult:
        ...

    def write_record(self, payload: dict[str, Any]) -> ConnectorResult:
        ...

    def read_records(self, query: dict[str, Any] | None = None) -> ConnectorResult:
        ...
