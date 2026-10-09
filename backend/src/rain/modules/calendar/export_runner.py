"""Re-runs a saved rain.db.tenant_models.ExportProfile with no HTTP
request/form in play -- what rain.modules.calendar.sweep needs to fire a
calendar entry's "run a saved export profile" trigger unattended, unlike
rain.modules.tickets.router/rain.modules.assets.router's own export_run,
which always has a submitted form (Type/Status filters, an uploaded
one-off .jq file, ...) to read from.

A saved profile's own `columns` is already exactly the shape `build_rows`
wants, in final order -- export_run only ever stores the columns a user
actually checked, already sorted by `order`, before calling
save_export_profile (see both routers' own export_run), so there's no
separate "which columns were checked" step to redo here the way
rain.core.export_columns.merge_profile_columns does for the *form*
rendering case.

Ticket-scoped profiles carry no saved Type/Status filter (ExportProfile
has no column for either) -- a profile never captured one even on a
manual re-run from the export screen (loading a profile doesn't restore
those two plain form fields), so an unattended run matches that same
"every ticket, regardless of type/status" scope, not a new limitation
introduced here."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.jq_transform import apply_jq_filter
from rain.db.tenant_models import ExportProfile
from rain.modules.assets import exporter as asset_exporter
from rain.modules.documents import service as document_service
from rain.modules.tickets import exporter as ticket_exporter


async def run_saved_export_profile(db: AsyncSession, profile: ExportProfile) -> str:
    """Returns the exported JSON/CSV text, jq-transformed if the profile
    has a ruleset document picked. xlsx profiles aren't runnable this
    way -- see save_to_document's own migration docstring; the export
    screens already refuse to save an xlsx profile with a document
    destination, so profile.format is "csv" or "json" here by
    construction."""
    headers = [c["header"] for c in profile.columns]
    if profile.scope == "ticket":
        rows = await ticket_exporter.build_rows(db, ticket_type=None, status=None, columns=profile.columns)
        body = ticket_exporter.render_json(rows) if profile.format == "json" else ticket_exporter.render_csv(rows, headers)
    else:
        rows = await asset_exporter.build_rows(db, asset_type_id=profile.asset_type_id, columns=profile.columns)
        body = asset_exporter.render_json(rows) if profile.format == "json" else asset_exporter.render_csv(rows, headers)

    if profile.jq_document_id:
        jq_filter_text = await document_service.get_document_text_body(db, profile.jq_document_id)
        if jq_filter_text:
            body = apply_jq_filter(rows, jq_filter_text)

    return body
