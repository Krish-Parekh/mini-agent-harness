from __future__ import annotations

import base64
import logging
import os

import logfire

from miniagent.config import Settings

_log = logging.getLogger(__name__)
_SERVICE_NAME = "miniagent"


def _langfuse_endpoint(settings: Settings) -> tuple[str, str] | None:
    if not (
        settings.langfuse_base_url
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    ):
        return None
    auth = base64.b64encode(
        f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
    ).decode()
    endpoint = f"{settings.langfuse_base_url.rstrip('/')}/api/public/otel"
    return endpoint, f"Authorization=Basic {auth}"


def configure(settings: Settings) -> bool:
    target = _langfuse_endpoint(settings)
    if target is not None:
        endpoint, headers = target
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = headers

    logfire.configure(
        service_name=_SERVICE_NAME,
        send_to_logfire=False,
        console=False,
    )

    if target is None:
        _log.warning(
            "Langfuse is not configured; spans are recorded but exported nowhere. "
            "Set LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY."
        )
    return target is not None
