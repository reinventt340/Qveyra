"""Extensible, configuration-driven financial data connectors."""

from app.services.integrations.base import Connector, ConnectorResult
from app.services.integrations.registry import configured_connectors

__all__ = ["Connector", "ConnectorResult", "configured_connectors"]
