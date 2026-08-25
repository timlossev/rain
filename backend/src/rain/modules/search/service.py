"""Keyword search across Tickets, Documents, and Assets.

Tickets/Documents: Postgres full-text search (the generated
`search_vector` columns + GIN index added by tenant migration 0023),
ranked with ts_rank. A Document's optional tags (migration 0039) are
folded into its search_vector too, at the same weight as its
description -- nothing here has to know tags exist; they're just
already part of what ts_rank/ts_headline are scoring/highlighting
against. Assets have no search_vector column -- there's no
free-text title/description to feed a tsvector, just a name plus
external_id/ci_number and arbitrary EAV custom field values -- so they're
matched with the same ILIKE "contains" logic the Assets list's own search
box uses (rain.modules.assets.service.asset_search_filter), given a fixed
rank rather than a real ts_rank score (see search() below).

No vector/semantic search: that needs an embedding source (a local model
or an API) to turn a query into a vector in the first place, and this
app doesn't have one wired in. `Ticket.embedding`/`Document.embedding`
(pgvector, enabled -- see control migration 0006) are reserved for
exactly that once one exists; nothing computes or searches against them
today, so this module only ever does keyword search.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from markupsafe import Markup, escape
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.db.tenant_models import Asset, Document, Ticket
from rain.modules.assets import service as assets_service

# Recognizes a ticket/document/asset number typed by hand, tolerant of a
# missing or partial zero-pad (e.g. "inc-1" as well as "INC-000001") --
# every number the app itself ever displays is already zero-padded to 6
# digits, but someone typing one from memory won't necessarily match that
# exactly.
_NUMBER_RE = re.compile(r"^(INC|VULN|CHG|DOC|CI)-0*(\d+)$", re.IGNORECASE)

# ts_rank on a real keyword match typically lands well under 1.0 for
# ordinary title/description text -- this sits comfortably inside that
# range so an asset ILIKE hit surfaces alongside ticket/document matches
# instead of always trailing every one of them (or, at 0, needing a
# tie-break rule of its own).
_ASSET_RANK = 0.1

# Sentinel bytes ts_headline wraps a match in -- swapped for real <mark>
# tags only *after* escaping the rest of the snippet (see _headline_to_html),
# so a match highlight can never smuggle in unescaped HTML from a
# ticket/document's own (user-authored, never sanitized) title/description.
_HL_START, _HL_STOP = "\x01", "\x02"


@dataclass
class SearchResult:
    kind: str  # "ticket" | "document" | "asset"
    id: int
    number: str
    title: str
    snippet: Markup | None
    href: str


def _headline_to_html(raw: str | None) -> Markup | None:
    if not raw:
        return None
    escaped = str(escape(raw))
    return Markup(escaped.replace(_HL_START, "<mark>").replace(_HL_STOP, "</mark>"))


async def find_by_number(db: AsyncSession, query: str) -> SearchResult | None:
    """An exact ticket/document/asset number takes the searcher straight to
    that one record instead of a results page that would just contain it
    among (possibly) other matches -- checked before search() below runs
    at all, same as a ticket/document number."""
    match = _NUMBER_RE.match(query.strip())
    if not match:
        return None
    prefix, digits = match.group(1).upper(), match.group(2)
    number = f"{prefix}-{int(digits):06d}"

    if prefix == "DOC":
        result = await db.execute(select(Document).where(Document.doc_number == number))
        doc = result.scalar_one_or_none()
        if doc is None:
            return None
        return SearchResult(kind="document", id=doc.id, number=doc.doc_number, title=doc.title, snippet=None, href=f"/documents/{doc.doc_number}")

    if prefix == "CI":
        result = await db.execute(select(Asset).where(Asset.ci_number == number))
        asset = result.scalar_one_or_none()
        if asset is None:
            return None
        return SearchResult(kind="asset", id=asset.id, number=asset.ci_number, title=asset.name, snippet=None, href=f"/assets/{asset.ci_number}/edit")

    result = await db.execute(select(Ticket).where(Ticket.ticket_number == number))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        return None
    return SearchResult(kind="ticket", id=ticket.id, number=ticket.ticket_number, title=ticket.title, snippet=None, href=f"/tickets/{ticket.ticket_number}")


async def search(db: AsyncSession, query: str, *, limit_per_kind: int = 25) -> list[SearchResult]:
    """Top matches from each of tickets, documents, and assets (ranked
    independently -- ts_rank isn't comparable across two different
    tsvector expressions, and assets have no tsvector at all, see
    _ASSET_RANK above), merged and re-sorted by rank. Small-enough result
    sets in practice that doing the merge in Python instead of a single
    UNION query is simpler and not a real cost."""
    query = query.strip()
    if not query:
        return []

    # websearch_to_tsquery parses the query the way a search engine's box
    # would -- quoted phrases, OR, -exclusions -- so it tolerates
    # arbitrary typed-in text instead of raising on it the way
    # plainto_tsquery's stricter sibling, to_tsquery, would.
    tsquery = func.websearch_to_tsquery("english", query)
    headline_opts = "StartSel=\x01, StopSel=\x02, MaxWords=30, MinWords=15, HighlightAll=false"

    ticket_rank = func.ts_rank(Ticket.search_vector, tsquery)
    ticket_headline = func.ts_headline(
        "english", func.coalesce(Ticket.title, "") + ". " + func.coalesce(Ticket.description, ""), tsquery, headline_opts
    )
    ticket_stmt = (
        select(Ticket, ticket_rank.label("rank"), ticket_headline.label("headline"))
        .where(Ticket.search_vector.op("@@")(tsquery))
        .order_by(ticket_rank.desc())
        .limit(limit_per_kind)
    )

    doc_rank = func.ts_rank(Document.search_vector, tsquery)
    # Tags folded into the headline source text too (not just search_vector
    # itself) -- otherwise a document that only matched via a tag (nothing
    # in title/description) would ts_headline down to an empty/misleading
    # snippet despite being a real, ranked hit.
    doc_headline = func.ts_headline(
        "english",
        func.coalesce(Document.title, "")
        + ". "
        + func.coalesce(func.array_to_string(Document.tags, ", "), "")
        + ". "
        + func.coalesce(Document.description, ""),
        tsquery,
        headline_opts,
    )
    doc_stmt = (
        select(Document, doc_rank.label("rank"), doc_headline.label("headline"))
        .where(Document.search_vector.op("@@")(tsquery))
        .order_by(doc_rank.desc())
        .limit(limit_per_kind)
    )

    # No tsvector/ts_rank for assets (see this module's docstring) -- given
    # _ASSET_RANK, a fixed middling score, instead of 0, so a handful of
    # asset hits don't get buried at the very bottom of a large ticket/
    # document result set, but a strong keyword match on a ticket/document
    # title still outranks them.
    asset_stmt = (
        select(Asset)
        .options(selectinload(Asset.asset_type))
        .where(assets_service.asset_search_filter(query))
        .order_by(Asset.name)
        .limit(limit_per_kind)
    )

    ticket_rows = (await db.execute(ticket_stmt)).all()
    doc_rows = (await db.execute(doc_stmt)).all()
    asset_rows = (await db.execute(asset_stmt)).scalars().all()

    results = [
        (
            rank,
            SearchResult(
                kind="ticket",
                id=t.id,
                number=t.ticket_number,
                title=t.title,
                snippet=_headline_to_html(headline),
                href=f"/tickets/{t.ticket_number}",
            ),
        )
        for t, rank, headline in ticket_rows
    ] + [
        (
            rank,
            SearchResult(
                kind="document",
                id=d.id,
                number=d.doc_number,
                title=d.title,
                snippet=_headline_to_html(headline),
                href=f"/documents/{d.doc_number}",
            ),
        )
        for d, rank, headline in doc_rows
    ] + [
        (
            _ASSET_RANK,
            SearchResult(
                kind="asset",
                id=a.id,
                number=a.ci_number,
                title=a.name,
                snippet=Markup(f"{escape(a.asset_type.name)} &middot; {escape(a.status)}") if a.asset_type else None,
                href=f"/assets/{a.ci_number}/edit",
            ),
        )
        for a in asset_rows
    ]
    results.sort(key=lambda pair: pair[0], reverse=True)
    return [r for _, r in results]
