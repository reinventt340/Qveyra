"""Configuration-based connector registration."""

from __future__ import annotations

import os

from app.services.integrations.base import Connector
from app.services.integrations.csv_sink import CsvConnector
from app.services.integrations.webhook import WebhookConnector


def configured_connectors() -> list[Connector]:
    """Build only connectors explicitly configured for this deployment."""
    tenant_id = os.getenv("DATA_SOURCE_TENANT_ID") or None
    connectors: list[Connector] = []
    webhook = WebhookConnector(os.getenv("DATA_SOURCE_WEBHOOK_URL"), tenant_id)
    csv_sink = CsvConnector(os.getenv("DATA_SOURCE_CSV_PATH"), tenant_id)
    if webhook.test_connection().configured:
        connectors.append(webhook)
    if csv_sink.test_connection().configured:
        connectors.append(csv_sink)
    return connectors
