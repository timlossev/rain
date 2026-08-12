"""The syslog listener: a TCP + UDP server the `worker` container runs,
meant to be configured as a syslog-ng destination (push model -- see
docs/architecture.md for the syslog-ng destination snippet). Newline-
delimited framing only (RFC 6587 non-transparent framing); octet-counted
TCP framing isn't supported yet.

Per received line: parse -> resolve tenant (control.syslog_source_map) ->
persist into that tenant's syslog_events -> publish to the live viewer ->
evaluate ticket_rules, auto-creating + notifying on a match.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging

from sqlalchemy import delete, select

from rain.core.tenant_config import get_tenant_config
from rain.db.base import control_session, tenant_session
from rain.db.control_models import Tenant
from rain.db.tenant_models import SyslogEvent
from rain.modules.tickets import rules
from rain.modules.tickets.live_bus import live_bus
from rain.modules.tickets.notifications import notify_ticket_created
from rain.modules.tickets.routing import resolve_tenant_for_event
from rain.modules.tickets.syslog_parser import parse_line, severity_label

logger = logging.getLogger("rain.syslog_listener")

MAX_LINE_BYTES = 32 * 1024
RETENTION_SWEEP_INTERVAL_SECONDS = 3600

_background_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def handle_raw_line(raw_line: str) -> None:
    try:
        raw_line = raw_line.strip()
        if not raw_line:
            return

        parsed = parse_line(raw_line)

        async with control_session() as control_db:
            tenant = await resolve_tenant_for_event(
                control_db, host=parsed.host, program=parsed.program, message=parsed.message
            )
        if tenant is None:
            logger.debug("no tenant matched host=%s program=%s; dropping event", parsed.host, parsed.program)
            return

        async with tenant_session(tenant.schema_name) as db:
            event = SyslogEvent(
                host=parsed.host,
                program=parsed.program,
                facility=parsed.facility,
                severity=parsed.severity,
                message=parsed.message[:8000],
                raw=parsed.raw[:8000],
            )
            db.add(event)
            await db.commit()
            # No db.refresh(event) -- see rain.modules.tickets.service.
            # create_ticket for why a refresh after commit is both
            # unnecessary (expire_on_commit=False) and actively broken
            # (loses this session's tenant schema_translate_map on the
            # fresh connection checkout).

            await live_bus.publish(
                tenant.schema_name,
                json.dumps(
                    {
                        "id": event.id,
                        "received_at": event.received_at.isoformat(),
                        "host": event.host,
                        "program": event.program,
                        "severity": event.severity,
                        "severity_label": severity_label(event.severity),
                        "message": event.message[:500],
                    }
                ),
            )

            matched_rule = await rules.find_matching_rule(db, event)
            if matched_rule is not None:
                ticket = await rules.apply_rule(db, matched_rule, event)
                await notify_ticket_created(db, ticket)
    except Exception:
        logger.exception("failed to handle syslog line: %r", raw_line[:200])


class _TCPProtocol(asyncio.Protocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport
        self._buffer = b""

    def data_received(self, data: bytes) -> None:
        self._buffer += data
        if len(self._buffer) > MAX_LINE_BYTES * 4:
            self._buffer = self._buffer[-MAX_LINE_BYTES:]  # guard against a sender that never sends '\n'
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            _spawn(handle_raw_line(line.decode("utf-8", errors="replace")))


class _UDPProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data: bytes, addr) -> None:
        _spawn(handle_raw_line(data.decode("utf-8", errors="replace")))


async def start_listener(host: str = "0.0.0.0", port: int = 5514):
    loop = asyncio.get_running_loop()
    tcp_server = await loop.create_server(_TCPProtocol, host, port)
    udp_transport, _ = await loop.create_datagram_endpoint(_UDPProtocol, local_addr=(host, port))
    logger.info("syslog listener up on %s:%s (tcp + udp)", host, port)
    return tcp_server, udp_transport


async def run_retention_sweep() -> None:
    """Trims each active tenant's syslog_events down to its configured
    retention window. Never deletes an event that was promoted into a
    ticket -- the ticket keeps its source_event_id valid."""
    async with control_session() as control_db:
        result = await control_db.execute(select(Tenant.schema_name).where(Tenant.is_active.is_(True)))
        schemas = list(result.scalars())

    for schema_name in schemas:
        try:
            async with tenant_session(schema_name) as db:
                retention_days = await get_tenant_config(db, "event_retention_days", 14)
                try:
                    retention_days = int(retention_days)
                except (TypeError, ValueError):
                    retention_days = 14
                cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=retention_days)
                await db.execute(
                    delete(SyslogEvent).where(SyslogEvent.received_at < cutoff, SyslogEvent.promoted_ticket_id.is_(None))
                )
                await db.commit()
        except Exception:
            logger.exception("retention sweep failed for schema %s", schema_name)


async def retention_loop() -> None:
    while True:
        await run_retention_sweep()
        await asyncio.sleep(RETENTION_SWEEP_INTERVAL_SECONDS)
