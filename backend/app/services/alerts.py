"""Alerts: failures are reported loudly instead of taking anything down.

Every alert is stored (shown in the UI's Alerts page and badge) and logged.
When ALERT_WEBHOOK_URL is set it is also POSTed there as {"text": ...} — the
format Slack, Microsoft Teams and most chat/incident tools accept for incoming
webhooks. The same alert is not repeated while an identical unacknowledged
one is still open, so a flapping service can't flood the channel.
"""
from __future__ import annotations

import logging
import threading
from datetime import timedelta

import httpx
from sqlmodel import Session, select

from app.core.config import settings
from app.models.models import Alert, utcnow

log = logging.getLogger("intent2deploy.alerts")
_lock = threading.Lock()
_DEDUP_WINDOW = timedelta(minutes=10)
_ICONS = {"CRITICAL": "🔴", "WARNING": "🟠", "INFO": "🟢"}
engine_override = None  # tests point alerts at their own database


def _engine():  # noqa: ANN202
    from app.core.db import engine

    return engine_override or engine


def raise_alert(
    severity: str, source: str, title: str, detail: str = "", deployment: str = "", workflow_id: str | None = None
) -> Alert | None:
    """Record (and send) an alert. Returns None when it duplicates an open one.
    Never raises: alerting must not break the thing it reports on."""
    try:
        with _lock, Session(_engine()) as session:
            recent = session.exec(
                select(Alert).where(
                    Alert.title == title, Alert.deployment == deployment, Alert.acknowledged == False,  # noqa: E712
                    Alert.created_at >= utcnow() - _DEDUP_WINDOW,
                )
            ).first()
            if recent is not None:
                return None
            alert = Alert(severity=severity, source=source, title=title, detail=detail[:4000],
                          deployment=deployment, workflow_id=workflow_id)
            if _send_webhook(alert):
                alert.delivered_to = "webhook"
            session.add(alert)
            session.commit()
            session.refresh(alert)
    except Exception:  # noqa: BLE001 - see docstring
        log.exception("Could not record alert %r", title)
        return None
    level = logging.ERROR if severity == "CRITICAL" else logging.WARNING if severity == "WARNING" else logging.INFO
    log.log(level, "[%s] %s — %s", severity, title, detail[:300])
    return alert


def _send_webhook(alert: Alert) -> bool:
    url = settings.alert_webhook_url.strip()
    if not url:
        return False
    where = f" · {alert.deployment}" if alert.deployment else ""
    text = f"{_ICONS.get(alert.severity, '')} *{alert.severity}* {alert.title}{where}\n{alert.detail[:1500]}"
    try:
        return httpx.post(url, json={"text": text}, timeout=5).status_code < 300
    except httpx.HTTPError:
        log.warning("Alert webhook did not respond; the alert is still stored.")
        return False


def list_alerts(session: Session, limit: int = 100, open_only: bool = False) -> list[Alert]:
    query = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if open_only:
        query = query.where(Alert.acknowledged == False)  # noqa: E712
    return list(session.exec(query).all())


def open_counts(session: Session) -> dict[str, int]:
    counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
    for alert in session.exec(select(Alert).where(Alert.acknowledged == False)).all():  # noqa: E712
        counts[alert.severity] = counts.get(alert.severity, 0) + 1
    return counts


def acknowledge(session: Session, alert_id: str | None = None) -> int:
    """Acknowledge one alert, or all open ones when no id is given."""
    query = select(Alert).where(Alert.acknowledged == False)  # noqa: E712
    if alert_id:
        query = query.where(Alert.id == alert_id)
    rows = session.exec(query).all()
    for row in rows:
        row.acknowledged = True
        session.add(row)
    session.commit()
    return len(rows)
