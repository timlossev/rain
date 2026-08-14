from __future__ import annotations

from sqlalchemy import Sequence, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.db.tenant_models import Document, DocumentLink


async def _next_doc_number(db: AsyncSession) -> str:
    seq = Sequence("doc_number_seq")
    next_val = await db.scalar(select(seq.next_value()))
    return f"DOC-{next_val:06d}"


async def create_document(
    db: AsyncSession,
    *,
    title: str,
    description: str | None,
    filename: str,
    storage_key: str,
    mime_type: str | None,
    size_bytes: int,
    uploaded_by: int | None,
) -> Document:
    doc = Document(
        doc_number=await _next_doc_number(db),
        title=title,
        description=description,
        filename=filename,
        storage_key=storage_key,
        mime_type=mime_type,
        size_bytes=size_bytes,
        uploaded_by=uploaded_by,
    )
    db.add(doc)
    await db.commit()
    # No db.refresh(doc) -- see rain.modules.tickets.service.create_ticket
    # for why a refresh after commit is both unnecessary
    # (expire_on_commit=False) and actively broken (loses this session's
    # tenant schema_translate_map on the fresh connection checkout).
    return doc


def document_list_stmt(*, search: str | None = None):
    stmt = select(Document).order_by(Document.created_at.desc())
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Document.title.ilike(like) | Document.doc_number.ilike(like))
    return stmt


async def list_documents(db: AsyncSession, *, search: str | None = None) -> list[Document]:
    result = await db.execute(document_list_stmt(search=search))
    return list(result.scalars())


async def get_document(db: AsyncSession, document_id: int) -> Document | None:
    stmt = select(Document).where(Document.id == document_id).options(selectinload(Document.links))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_body_size(db: AsyncSession, doc: Document, size_bytes: int) -> None:
    doc.size_bytes = size_bytes
    await db.commit()


async def delete_document(db: AsyncSession, document: Document) -> None:
    await db.delete(document)  # cascades to document_links
    await db.commit()


async def add_link(db: AsyncSession, document_id: int, linked_type: str, linked_id: int, created_by: int | None) -> DocumentLink:
    link = DocumentLink(document_id=document_id, linked_type=linked_type, linked_id=linked_id, created_by=created_by)
    db.add(link)
    await db.commit()
    return link


async def remove_link(db: AsyncSession, link_id: int) -> DocumentLink | None:
    """Returns the now-deleted link (document eager-loaded) rather than
    None on success -- the caller (documents/router.py) needs
    linked_type/linked_id/document.title *after* the delete to decide
    whether to log it to a ticket's activity feed, and a plain id isn't
    enough to look either back up post-delete."""
    link = await db.get(DocumentLink, link_id, options=[selectinload(DocumentLink.document)])
    if link is not None:
        await db.delete(link)
        await db.commit()
    return link


async def links_for(db: AsyncSession, linked_type: str, linked_id: int) -> list[DocumentLink]:
    stmt = (
        select(DocumentLink)
        .where(DocumentLink.linked_type == linked_type, DocumentLink.linked_id == linked_id)
        .options(selectinload(DocumentLink.document))
        .order_by(DocumentLink.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars())
