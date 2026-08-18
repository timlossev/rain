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
from rain.modules.tickets import correlation, rules
from rain.modules.tickets.event_formats import detect_and_parse, summarize
from rain.modules.tickets.live_bus import live_bus
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

        # CEF/JSON/kv-shaped message bodies (most SIEMs/EDRs -- Wazuh
        # included -- can emit any of the three) get recognized here and
        # turned into a readable summary + the fields their own parser
        # extracted, rather than staying an opaque blob. Standard syslog
        # text (event_format == "plain") is untouched -- same behavior
        # as before this existed.
        event_format, parsed_fields = detect_and_parse(parsed.message)
        message = summarize(event_format, parsed_fields, parsed.message) if parsed_fields else parsed.message

        async with control_session() as control_db:
            tenant = await resolve_tenant_for_event(
                control_db, host=parsed.host, program=parsed.program, message=message
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
                message=message[:8000],
                raw=parsed.raw[:8000],
                event_format=event_format,
                parsed_fields=parsed_fields,
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
                        "event_format": event.event_format,
                    }
                ),
            )

            matched_rule = await rules.find_matching_rule(db, event)
            if matched_rule is not None:
                # apply_rule() -> service.create_ticket() already evaluates
                # Platform Event rules (notify Slack/email/webhook/etc, if
                # any are configured to match) -- no separate notify step
                # needed here.
                await rules.apply_rule(db, matched_rule, event)

            # Correlation Rules (multi-event: "N matching events within
            # T minutes") run independently of the single-event match
            # above -- an event can both promote itself via a TicketRule
            # *and* contribute to a Correlation Rule's count.
            await correlation.evaluate_correlation_rules(db, event)
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
                retention_hours = await get_tenant_config(db, "event_retention_hours", 12)
                try:
                    retention_hours = float(retention_hours)
                except (TypeError, ValueError):
                    retention_hours = 12
                cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=retention_hours)
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
