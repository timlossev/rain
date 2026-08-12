"""Offset-based pagination shared by every list screen in the app. Kept as
a small helper rather than a library dependency -- the pattern is the same
everywhere: take `page` from the query string, run a COUNT + LIMIT/OFFSET
query, hand the template a Page with just enough to render prev/next and
a "showing X-Y of Z" line.

Only ever used with statements built via `select(SomeModel)...` (optionally
with `selectinload(...)` options) -- selectinload issues its related-row
fetch as a *separate* query rather than adding columns/joins to this one,
so wrapping the statement in a subquery for the COUNT is safe. This would
NOT be safe for joinedload, which this codebase deliberately avoids
everywhere for exactly this kind of reason (see rain.db.base's module
docs on selectinload as the established eager-load pattern)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 25


@dataclass
class Page(Generic[T]):
    items: Sequence[T]
    page: int
    page_size: int
    total: int

    @property
    def total_pages(self) -> int:
        return max(1, -(-self.total // self.page_size))

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def start_index(self) -> int:
        return 0 if self.total == 0 else (self.page - 1) * self.page_size + 1

    @property
    def end_index(self) -> int:
        return min(self.page * self.page_size, self.total)


async def paginate(db: AsyncSession, stmt: Select, *, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> Page:
    page = max(1, page)
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await db.execute(count_stmt)).scalar_one()
    result = await db.execute(stmt.limit(page_size).offset((page - 1) * page_size))
    items = list(result.scalars())
    return Page(items=items, page=page, page_size=page_size, total=total)
