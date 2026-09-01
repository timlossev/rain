"""Export/import for RAIN's two configuration bundle kinds -- see Admin >
Config Bundles (this module backs both cards there).

**Platform bundle** (`rain_platform_config`): everything that's genuinely
instance-wide in this schema -- branding (instance name, accent color,
font, logo, and the client portal's background image; all of these live
in `control.global_config`, one set for the whole install, not per
tenant), the SMTP relay, the LDAP and SAML provider configs (each is a
single row for the whole instance, pointed at one target tenant -- see
rain.modules.auth.ldap_config's own docstring for why RAIN doesn't
support one directory per tenant), and syslog source routing rules.

**Tenant bundle** (`rain_tenant_config`): one tenant's own configuration
-- asset types, custom fields, ticket statuses, groups and local users,
notification channels, webhooks, approval flows, Event Promotion
Policies, Platform Response Rules, and Service Catalog items. Explicitly
excludes any actual DATA (tickets, assets, documents, syslog events) and
the ML rule sidecar's trained runtime state (TicketRuleState) -- neither
is "configuration" in the sense this bundle means, and neither has a
sane meaning transplanted onto a different tenant/instance.

The two bundle kinds are deliberately independent -- importing one never
requires the other to have been imported first (though a syslog source
rule or an LDAP/SAML config in a platform bundle that targets a specific
tenant only takes effect once a tenant with that slug exists on the
target instance).

Every cross-reference inside a bundle (a Platform Response Rule action's
notification channel, an approval step's group, a Service Catalog item's
approval flow, ...) is resolved by *name* at export time and re-resolved
by name again at import time -- never a raw database id, which means
nothing on a different instance. A reference to actual data (a Platform
Response Rule's "attach a document" action, a Service Catalog field
sourced from a specific document) has no portable equivalent at all and
is dropped, with a note in the bundle's own "warnings" list explaining
why -- these are the two possible "does this survive the round trip"
gaps discussed when this was scoped out, made explicit and visible
rather than silently produced.

Secrets (the LDAP bind password, the SMTP password, a Slack/email
notification channel's config, a webhook's headers) are decrypted into
the bundle only when the exporting admin explicitly opts in
(`include_secrets=True`) -- off by default, matching this app's general
"locked down unless explicitly opted into" posture elsewhere
(portal_require_auth, portal_branded, ...). A bundle exported without
secrets stays structurally complete (every other field, and a `"_redacted":
true` marker so it's obvious what's missing) rather than silently
omitting those keys, so it's still useful for review or partial editing
before a secrets-included export gets layered on top.

Every entity is upserted by its natural key (name/key/email) on import,
not always-inserted -- re-importing the same bundle (or an edited copy of
one) updates the matching rows instead of duplicating them. The one
exception is local users: an existing account is left untouched rather
than having its password/role silently overwritten by a re-import.
"""
from __future__ import annotations

import base64
import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.core.config_store import FONT_CHOICES, config_store
from rain.core.crypto import decrypt_json, encrypt_json
from rain.core.tenant_config import DEFAULTS as TENANT_CONFIG_DEFAULTS
from rain.core.tenant_config import get_tenant_configs, set_tenant_configs
from rain.db.base import control_session
from rain.db.control_models import SyslogSourceMap, Tenant, User
from rain.db.tenant_models import (
    ApprovalFlow,
    ApprovalFlowStep,
    AssetType,
    CustomField,
    Group,
    GroupMembership,
    NotificationChannel,
    PlatformEventAction,
    PlatformEventRule,
    ServiceCatalogField,
    ServiceCatalogItem,
    TicketRule,
    TicketStatus,
    WebhookConfig,
)
from rain.modules.auth import ldap_config, saml_config
from rain.web.uploads import read_local_branding_file, save_logo_bytes, save_portal_background_bytes

PLATFORM_BUNDLE_TYPE = "rain_platform_config"
TENANT_BUNDLE_TYPE = "rain_tenant_config"
BUNDLE_VERSION = 1


@dataclass
class BundleResult:
    """What apply_*_bundle actually did -- counts by category (created and
    updated counted separately, e.g. "asset types" vs "asset types
    (updated)") plus every reference this instance couldn't resolve, so
    an admin sees exactly what needs a manual follow-up rather than a
    bare "import succeeded"."""

    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def bump(self, category: str, n: int = 1) -> None:
        if n:
            self.counts[category] = self.counts.get(category, 0) + n


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _encode_image(path: str | None) -> dict | None:
    found = read_local_branding_file(path)
    if found is None:
        return None
    data, content_type, filename = found
    return {"filename": filename, "content_type": content_type, "data_base64": base64.b64encode(data).decode("ascii")}


# ---------------------------------------------------------------------
# Platform bundle
# ---------------------------------------------------------------------


async def build_platform_bundle(*, include_secrets: bool) -> dict:
    warnings: list[str] = []

    branding = {
        "instance_name": config_store.get("instance_name"),
        "accent_color": config_store.get("accent_color"),
        "font_family": config_store.get("font_family"),
        "logo": _encode_image(config_store.get("logo_path")),
        "portal_background": _encode_image(config_store.get("portal_background_path")),
    }

    smtp: dict[str, Any] = {
        "host": config_store.get("smtp_host") or "",
        "port": config_store.get("smtp_port") or 587,
        "username": config_store.get("smtp_username") or "",
        "from_address": config_store.get("smtp_from_address") or "",
        "use_tls": bool(config_store.get("smtp_use_tls")),
        "password": None,
    }
    encrypted_smtp_password = config_store.get("smtp_password_encrypted")
    if include_secrets:
        smtp["password"] = decrypt_json(bytes.fromhex(encrypted_smtp_password)) if encrypted_smtp_password else None
    elif encrypted_smtp_password:
        smtp["password_redacted"] = True
        warnings.append("SMTP password redacted -- re-enter it in Admin > SMTP Relay after import.")

    async with control_session() as session:
        tenant_slug_by_id = {t.id: t.slug for t in (await session.execute(select(Tenant))).scalars()}

        ldap_data = None
        ldap_row = await ldap_config.get_provider_row(session)
        if ldap_row is not None:
            raw = await ldap_config.get_raw_config(session)
            ldap_data = {k: v for k, v in raw.items() if k != "target_tenant_id"}
            ldap_data["is_enabled"] = ldap_row.is_enabled
            ldap_data["target_tenant_slug"] = tenant_slug_by_id.get(raw.get("target_tenant_id"))
            if include_secrets:
                pass
            elif ldap_data.get("bind_password"):
                ldap_data["bind_password"] = ""
                ldap_data["password_redacted"] = True
                warnings.append("LDAP bind password redacted -- re-enter it in Admin > Auth Providers > LDAP after import.")

        saml_data = None
        saml_row = await saml_config.get_provider_row(session)
        if saml_row is not None:
            raw = await saml_config.get_raw_config(session)
            saml_data = {k: v for k, v in raw.items() if k != "target_tenant_id"}
            saml_data["is_enabled"] = saml_row.is_enabled
            saml_data["target_tenant_slug"] = tenant_slug_by_id.get(raw.get("target_tenant_id"))

        source_rows = (await session.execute(select(SyslogSourceMap).order_by(SyslogSourceMap.sort_order))).scalars()
        syslog_sources = [
            {
                "match_field": row.match_field,
                "pattern": row.pattern,
                "is_regex": row.is_regex,
                "action": row.action,
                "sort_order": row.sort_order,
                "is_active": row.is_active,
                "target_tenant_slug": tenant_slug_by_id.get(row.tenant_id),
            }
            for row in source_rows
        ]

    return {
        "bundle_type": PLATFORM_BUNDLE_TYPE,
        "bundle_version": BUNDLE_VERSION,
        "exported_at": _now_iso(),
        "secrets_included": include_secrets,
        "branding": branding,
        "smtp": smtp,
        "ldap": ldap_data,
        "saml": saml_data,
        "syslog_sources": syslog_sources,
        "warnings": warnings,
    }


async def apply_platform_bundle(data: dict, *, updated_by: int) -> BundleResult:
    if data.get("bundle_type") != PLATFORM_BUNDLE_TYPE:
        raise ValueError(f"not a platform configuration bundle (bundle_type={data.get('bundle_type')!r})")
    result = BundleResult()

    branding = data.get("branding") or {}
    if branding.get("instance_name"):
        await config_store.set("instance_name", branding["instance_name"], updated_by=updated_by)
        result.bump("branding fields")
    if branding.get("accent_color"):
        await config_store.set("accent_color", branding["accent_color"], updated_by=updated_by)
        result.bump("branding fields")
    allowed_fonts = {css for _, css in FONT_CHOICES}
    if branding.get("font_family") in allowed_fonts:
        await config_store.set("font_family", branding["font_family"], updated_by=updated_by)
        result.bump("branding fields")

    logo = branding.get("logo")
    if logo:
        try:
            raw = base64.b64decode(logo["data_base64"])
            path = await save_logo_bytes(raw, logo.get("content_type", "image/png"), logo.get("filename", ""))
            await config_store.set("logo_path", path, updated_by=updated_by)
            result.bump("branding images")
        except Exception as exc:
            result.warnings.append(f"Logo: could not import image ({exc}).")

    background = branding.get("portal_background")
    if background:
        try:
            raw = base64.b64decode(background["data_base64"])
            path = await save_portal_background_bytes(
                raw, background.get("content_type", "image/png"), background.get("filename", "")
            )
            await config_store.set("portal_background_path", path, updated_by=updated_by)
            result.bump("branding images")
        except Exception as exc:
            result.warnings.append(f"Client portal background: could not import image ({exc}).")

    smtp = data.get("smtp") or {}
    if smtp.get("host"):
        await config_store.set("smtp_host", smtp["host"], updated_by=updated_by)
        await config_store.set("smtp_port", smtp.get("port", 587), updated_by=updated_by)
        await config_store.set("smtp_username", smtp.get("username", ""), updated_by=updated_by)
        await config_store.set("smtp_from_address", smtp.get("from_address", ""), updated_by=updated_by)
        await config_store.set("smtp_use_tls", bool(smtp.get("use_tls")), updated_by=updated_by)
        result.bump("SMTP settings")
        if smtp.get("password"):
            await config_store.set("smtp_password_encrypted", encrypt_json(smtp["password"]).hex(), updated_by=updated_by)
        elif smtp.get("password_redacted"):
            result.warnings.append("SMTP password was redacted in the bundle -- re-enter it in Admin > SMTP Relay.")

    async with control_session() as session:
        tenant_id_by_slug = {t.slug: t.id for t in (await session.execute(select(Tenant))).scalars()}

        ldap_data = data.get("ldap")
        if ldap_data:
            fields = {k: v for k, v in ldap_data.items() if k not in ("is_enabled", "target_tenant_slug", "password_redacted")}
            target_slug = ldap_data.get("target_tenant_slug")
            target_id = tenant_id_by_slug.get(target_slug) if target_slug else None
            if target_slug and target_id is None:
                result.warnings.append(
                    f"LDAP: target tenant '{target_slug}' doesn't exist here -- imported disabled; "
                    "pick a tenant in Admin > Auth Providers > LDAP."
                )
            fields["target_tenant_id"] = target_id
            await ldap_config.save_ldap_config(
                session, is_enabled=bool(ldap_data.get("is_enabled")) and target_id is not None, **fields
            )
            result.bump("LDAP configuration")
            if ldap_data.get("password_redacted"):
                result.warnings.append("LDAP bind password was redacted in the bundle -- re-enter it in Admin > Auth Providers > LDAP.")

        saml_data = data.get("saml")
        if saml_data:
            fields = {k: v for k, v in saml_data.items() if k not in ("is_enabled", "target_tenant_slug")}
            target_slug = saml_data.get("target_tenant_slug")
            target_id = tenant_id_by_slug.get(target_slug) if target_slug else None
            if target_slug and target_id is None:
                result.warnings.append(
                    f"SAML: target tenant '{target_slug}' doesn't exist here -- imported disabled; "
                    "pick a tenant in Admin > Auth Providers > SAML."
                )
            fields["target_tenant_id"] = target_id
            await saml_config.save_saml_config(
                session, is_enabled=bool(saml_data.get("is_enabled")) and target_id is not None, **fields
            )
            result.bump("SAML configuration")

        for src in data.get("syslog_sources", []):
            target_slug = src.get("target_tenant_slug")
            target_id = tenant_id_by_slug.get(target_slug) if target_slug else None
            if src.get("action", "route") == "route" and target_slug and target_id is None:
                result.warnings.append(
                    f"Syslog source rule ({src.get('match_field')}={src.get('pattern')!r}) targets tenant "
                    f"'{target_slug}', which doesn't exist here -- skipped."
                )
                continue
            session.add(
                SyslogSourceMap(
                    tenant_id=target_id,
                    match_field=src["match_field"],
                    pattern=src["pattern"],
                    is_regex=bool(src.get("is_regex")),
                    action=src.get("action", "route"),
                    sort_order=src.get("sort_order", 0),
                    is_active=bool(src.get("is_active", True)),
                )
            )
            result.bump("syslog source rules")
        await session.commit()

    return result


# ---------------------------------------------------------------------
# Tenant bundle
# ---------------------------------------------------------------------


async def _upsert_by_key(tenant_db: AsyncSession, model: type, key_column: str, key_value: str, set_fields: dict) -> tuple[Any, bool]:
    row = (await tenant_db.execute(select(model).where(getattr(model, key_column) == key_value))).scalar_one_or_none()
    created = row is None
    if row is None:
        row = model(**{key_column: key_value})
        tenant_db.add(row)
    for name, value in set_fields.items():
        setattr(row, name, value)
    await tenant_db.flush()
    return row, created


async def build_tenant_bundle(tenant_db: AsyncSession, tenant: Tenant, *, include_secrets: bool) -> dict:
    warnings: list[str] = []

    async with control_session() as control_db:
        tenant_users = list((await control_db.execute(select(User).where(User.tenant_id == tenant.id))).scalars())
    user_email_by_id = {u.id: u.email for u in tenant_users}

    asset_types = list((await tenant_db.execute(select(AssetType).order_by(AssetType.sort_order, AssetType.name))).scalars())
    asset_type_key_by_id = {a.id: a.key for a in asset_types}
    custom_fields = list((await tenant_db.execute(select(CustomField))).scalars())
    ticket_statuses = list((await tenant_db.execute(select(TicketStatus).order_by(TicketStatus.sort_order))).scalars())

    groups = list((await tenant_db.execute(select(Group).order_by(Group.name))).scalars())
    group_name_by_id = {g.id: g.name for g in groups}
    memberships = list((await tenant_db.execute(select(GroupMembership))).scalars())

    webhooks = list((await tenant_db.execute(select(WebhookConfig).order_by(WebhookConfig.name))).scalars())
    webhook_name_by_id = {w.id: w.name for w in webhooks}

    channels = list((await tenant_db.execute(select(NotificationChannel).order_by(NotificationChannel.name))).scalars())
    channel_name_by_id = {c.id: c.name for c in channels}

    flows = list(
        (await tenant_db.execute(select(ApprovalFlow).options(selectinload(ApprovalFlow.steps)).order_by(ApprovalFlow.name))).scalars()
    )
    flow_name_by_id = {f.id: f.name for f in flows}

    event_policies = list((await tenant_db.execute(select(TicketRule).order_by(TicketRule.sort_order))).scalars())
    platform_rules = list(
        (
            await tenant_db.execute(
                select(PlatformEventRule).options(selectinload(PlatformEventRule.actions)).order_by(PlatformEventRule.sort_order)
            )
        ).scalars()
    )
    catalog_items = list(
        (
            await tenant_db.execute(
                select(ServiceCatalogItem).options(selectinload(ServiceCatalogItem.fields)).order_by(ServiceCatalogItem.sort_order)
            )
        ).scalars()
    )
    tenant_config_values = await get_tenant_configs(tenant_db, list(TENANT_CONFIG_DEFAULTS.keys()))

    asset_types_out = [
        {"key": a.key, "name": a.name, "icon": a.icon, "description": a.description, "is_active": a.is_active, "sort_order": a.sort_order}
        for a in asset_types
    ]

    custom_fields_out = [
        {
            "scope": f.scope,
            "asset_type_key": asset_type_key_by_id.get(f.asset_type_id) if f.asset_type_id else None,
            "field_key": f.field_key,
            "label": f.label,
            "field_type": f.field_type,
            "select_options": f.select_options,
            "is_required": f.is_required,
            "sort_order": f.sort_order,
        }
        for f in custom_fields
    ]

    ticket_statuses_out = [
        {"key": s.key, "label": s.label, "color": s.color, "is_closed": s.is_closed, "is_active": s.is_active, "sort_order": s.sort_order}
        for s in ticket_statuses
    ]

    groups_out = [{"name": g.name, "description": g.description, "source": g.source, "ldap_dn": g.ldap_dn} for g in groups]

    users_out = []
    skipped_non_local = 0
    for u in tenant_users:
        if u.auth_source != "local":
            skipped_non_local += 1
            continue
        entry = {"email": u.email, "display_name": u.display_name, "role_key": u.role_key, "is_active": u.is_active}
        if include_secrets:
            entry["password_hash"] = u.password_hash
        elif u.password_hash:
            entry["password_hash"] = None
            entry["password_redacted"] = True
        users_out.append(entry)
    if skipped_non_local:
        warnings.append(
            f"{skipped_non_local} LDAP/SAML-sourced user(s) not included -- re-created by their own sync/login "
            "flow on the target instance, not portable config."
        )
    if not include_secrets and users_out:
        warnings.append(
            f"{len(users_out)} local user(s) exported without a password hash -- re-export with secrets included "
            "to carry them, or each account is skipped on import."
        )

    memberships_out = []
    for m in memberships:
        group_name = group_name_by_id.get(m.group_id)
        user_email = user_email_by_id.get(m.user_id)
        if group_name is None or user_email is None:
            continue
        memberships_out.append({"group_name": group_name, "user_email": user_email})

    webhooks_out = []
    for w in webhooks:
        entry = {
            "name": w.name,
            "url": w.url,
            "http_method": w.http_method,
            "headers": w.headers if include_secrets else {},
            "payload_template": w.payload_template,
            "timeout_seconds": w.timeout_seconds,
            "success_codes": w.success_codes,
            "alert_on_failure": w.alert_on_failure,
        }
        if not include_secrets and w.headers:
            entry["headers_redacted"] = True
            warnings.append(f"Webhook '{w.name}': headers redacted -- re-enter them in Admin > Webhooks if it needs one (e.g. Authorization).")
        webhooks_out.append(entry)

    channels_out = []
    for c in channels:
        raw_config = decrypt_json(c.config_encrypted) if c.config_encrypted else {}
        if c.channel_type == "webhook":
            out_config: dict = {"webhook_name": webhook_name_by_id.get(raw_config.get("webhook_id"))}
            redacted = False
        elif include_secrets:
            out_config = raw_config
            redacted = False
        else:
            out_config = {}
            redacted = bool(raw_config)
        entry = {
            "name": c.name,
            "channel_type": c.channel_type,
            "config": out_config,
            "is_enabled": c.is_enabled,
            "message_template": c.message_template,
            "subject_template": c.subject_template,
        }
        if redacted:
            entry["config_redacted"] = True
            warnings.append(f"Notification channel '{c.name}': its recipient/webhook-URL config was redacted -- re-enter it after import.")
        channels_out.append(entry)

    flows_out = []
    for fl in flows:
        steps_out = []
        for st in sorted(fl.steps, key=lambda s: s.sort_order):
            approver_group_name = group_name_by_id.get(st.approver_group_id) if st.approver_group_id else None
            approver_user_email = user_email_by_id.get(st.approver_user_id) if st.approver_user_id else None
            if st.approver_group_id and approver_group_name is None:
                warnings.append(f"Approval flow '{fl.name}' step '{st.label}': approver group unresolved -- step exported with no assignee.")
            if st.approver_user_id and approver_user_email is None:
                warnings.append(f"Approval flow '{fl.name}' step '{st.label}': approver user unresolved -- step exported with no assignee.")
            steps_out.append(
                {
                    "sort_order": st.sort_order,
                    "label": st.label,
                    "approver_group_name": approver_group_name,
                    "approver_user_email": approver_user_email,
                }
            )
        flows_out.append(
            {"name": fl.name, "is_default": fl.is_default, "notify_syslog_on_approval": fl.notify_syslog_on_approval, "steps": steps_out}
        )

    event_policies_out = [
        {
            "name": r.name,
            "is_active": r.is_active,
            "promotion_type": r.promotion_type,
            "ticket_type": r.ticket_type,
            "match_field": r.match_field,
            "pattern": r.pattern,
            "title_template": r.title_template,
            "severity": r.severity,
            "asset_match_field": r.asset_match_field,
            "sort_order": r.sort_order,
            "group_by": r.group_by,
            "window_minutes": r.window_minutes,
            "ml_score_threshold": r.ml_score_threshold,
            "ml_warmup_count": r.ml_warmup_count,
            "ml_algorithm": r.ml_algorithm,
            "ml_sidecar_enabled": r.ml_sidecar_enabled,
            "approval_flow_name": flow_name_by_id.get(r.approval_flow_id) if r.approval_flow_id else None,
        }
        for r in event_policies
    ]

    platform_rules_out = []
    for rule in platform_rules:
        actions_out = []
        for action in rule.actions:
            cfg = action.config or {}
            entry = None
            if action.action_type in ("notify_slack", "notify_email"):
                channel_name = channel_name_by_id.get(cfg.get("channel_id"))
                if channel_name is None:
                    warnings.append(f"Platform Response Rule '{rule.name}': action '{action.action_type}' -- channel no longer exists, skipped.")
                else:
                    entry = {"action_type": action.action_type, "channel_name": channel_name}
            elif action.action_type == "webhook":
                webhook_name = webhook_name_by_id.get(cfg.get("webhook_id"))
                if webhook_name is None:
                    warnings.append(f"Platform Response Rule '{rule.name}': action 'webhook' -- webhook no longer exists, skipped.")
                else:
                    entry = {"action_type": "webhook", "webhook_name": webhook_name}
            elif action.action_type in ("attach_document", "attach_asset"):
                what = "document" if action.action_type == "attach_document" else "asset"
                warnings.append(
                    f"Platform Response Rule '{rule.name}': action '{action.action_type}' references a specific {what}, "
                    "which is data, not configuration -- skipped."
                )
            elif action.action_type == "mark_problematic":
                entry = {"action_type": "mark_problematic"}
            elif action.action_type == "add_watcher":
                email = (cfg.get("email") or "").strip() or user_email_by_id.get(cfg.get("user_id"), "")
                if email:
                    entry = {"action_type": "add_watcher", "email": email}
                else:
                    warnings.append(f"Platform Response Rule '{rule.name}': action 'add_watcher' has no resolvable email -- skipped.")
            else:
                entry = {"action_type": action.action_type, "config": cfg}
            if entry is not None:
                actions_out.append(entry)
        platform_rules_out.append(
            {
                "name": rule.name,
                "is_active": rule.is_active,
                "trigger_event": rule.trigger_event,
                "match_field": rule.match_field,
                "pattern": rule.pattern,
                "sort_order": rule.sort_order,
                "actions": actions_out,
            }
        )

    catalog_out = []
    for item in catalog_items:
        fields_out = []
        for f in sorted(item.fields, key=lambda x: x.sort_order):
            entry = {
                "field_key": f.field_key,
                "label": f.label,
                "field_type": f.field_type,
                "select_options": f.select_options,
                "is_required": f.is_required,
                "sort_order": f.sort_order,
                "source_mode": f.source_mode,
                "source_expression": f.source_expression,
            }
            if f.source_document_id is not None:
                entry["source_mode"] = None
                entry["source_expression"] = None
                warnings.append(
                    f"Service Catalog item '{item.name}' field '{f.label}': pulled its options from a specific document, "
                    "which is data, not configuration -- imported as a plain field instead."
                )
            fields_out.append(entry)
        catalog_out.append(
            {
                "key": item.key,
                "name": item.name,
                "description": item.description,
                "icon": item.icon,
                "ticket_type": item.ticket_type,
                "default_severity": item.default_severity,
                "payload_format": item.payload_format,
                "requires_approval": item.requires_approval,
                "approval_flow_name": flow_name_by_id.get(item.approval_flow_id) if item.approval_flow_id else None,
                "is_active": item.is_active,
                "sort_order": item.sort_order,
                "fields": fields_out,
            }
        )

    return {
        "bundle_type": TENANT_BUNDLE_TYPE,
        "bundle_version": BUNDLE_VERSION,
        "exported_at": _now_iso(),
        "source_tenant_slug": tenant.slug,
        "source_tenant_name": tenant.name,
        "secrets_included": include_secrets,
        "tenant_config": tenant_config_values,
        "asset_types": asset_types_out,
        "custom_fields": custom_fields_out,
        "ticket_statuses": ticket_statuses_out,
        "groups": groups_out,
        "users": users_out,
        "group_memberships": memberships_out,
        "webhooks": webhooks_out,
        "notification_channels": channels_out,
        "approval_flows": flows_out,
        "event_policies": event_policies_out,
        "platform_response_rules": platform_rules_out,
        "service_catalog": catalog_out,
        "warnings": warnings,
    }


async def apply_tenant_bundle(tenant_db: AsyncSession, tenant: Tenant, data: dict, *, updated_by: int) -> BundleResult:
    if data.get("bundle_type") != TENANT_BUNDLE_TYPE:
        raise ValueError(f"not a tenant configuration bundle (bundle_type={data.get('bundle_type')!r})")
    result = BundleResult()

    portable = {k: v for k, v in (data.get("tenant_config") or {}).items() if k in TENANT_CONFIG_DEFAULTS}
    if portable:
        await set_tenant_configs(tenant_db, portable, updated_by=updated_by)
        result.bump("tenant settings", len(portable))

    asset_type_id_by_key: dict[str, int] = {}
    for entry in data.get("asset_types", []):
        row, created = await _upsert_by_key(
            tenant_db,
            AssetType,
            "key",
            entry["key"],
            {
                "name": entry.get("name", entry["key"]),
                "icon": entry.get("icon"),
                "description": entry.get("description"),
                "is_active": entry.get("is_active", True),
                "sort_order": entry.get("sort_order", 0),
            },
        )
        asset_type_id_by_key[entry["key"]] = row.id
        result.bump("asset types" if created else "asset types (updated)")

    for entry in data.get("custom_fields", []):
        asset_type_key = entry.get("asset_type_key")
        asset_type_id = asset_type_id_by_key.get(asset_type_key) if asset_type_key else None
        if asset_type_key and asset_type_id is None:
            result.warnings.append(f"Custom field '{entry['field_key']}': asset type '{asset_type_key}' not found -- skipped.")
            continue
        existing = (
            await tenant_db.execute(
                select(CustomField).where(
                    CustomField.scope == entry["scope"], CustomField.asset_type_id == asset_type_id, CustomField.field_key == entry["field_key"]
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = CustomField(scope=entry["scope"], asset_type_id=asset_type_id, field_key=entry["field_key"])
            tenant_db.add(existing)
            result.bump("custom fields")
        else:
            result.bump("custom fields (updated)")
        existing.label = entry.get("label", entry["field_key"])
        existing.field_type = entry.get("field_type", "text")
        existing.select_options = entry.get("select_options")
        existing.is_required = entry.get("is_required", False)
        existing.sort_order = entry.get("sort_order", 0)
    await tenant_db.flush()

    for entry in data.get("ticket_statuses", []):
        _, created = await _upsert_by_key(
            tenant_db,
            TicketStatus,
            "key",
            entry["key"],
            {
                "label": entry.get("label", entry["key"]),
                "color": entry.get("color", "#6b7280"),
                "is_closed": entry.get("is_closed", False),
                "is_active": entry.get("is_active", True),
                "sort_order": entry.get("sort_order", 0),
            },
        )
        result.bump("ticket statuses" if created else "ticket statuses (updated)")

    group_id_by_name: dict[str, int] = {}
    for entry in data.get("groups", []):
        row, created = await _upsert_by_key(
            tenant_db,
            Group,
            "name",
            entry["name"],
            {"description": entry.get("description"), "source": entry.get("source", "local"), "ldap_dn": entry.get("ldap_dn")},
        )
        group_id_by_name[entry["name"]] = row.id
        result.bump("groups" if created else "groups (updated)")

    # Local users: control schema, tenant-scoped by tenant_id. Created
    # only, never overwritten -- a re-import must not silently reset an
    # existing account's password/role out from under an admin who's
    # since changed it by hand.
    user_id_by_email: dict[str, int] = {}
    async with control_session() as control_db:
        existing_users = {u.email: u for u in (await control_db.execute(select(User).where(User.tenant_id == tenant.id))).scalars()}
        for entry in data.get("users", []):
            email = entry["email"]
            existing = existing_users.get(email)
            if existing is not None:
                user_id_by_email[email] = existing.id
                result.warnings.append(f"User '{email}' already exists here -- left unchanged.")
                continue
            if not entry.get("password_hash"):
                result.warnings.append(f"User '{email}' has no password hash in this bundle -- skipped.")
                continue
            new_user = User(
                tenant_id=tenant.id,
                email=email,
                password_hash=entry["password_hash"],
                role_key=entry.get("role_key", "client"),
                display_name=entry.get("display_name", email),
                is_active=entry.get("is_active", True),
                auth_source="local",
            )
            control_db.add(new_user)
            await control_db.flush()
            user_id_by_email[email] = new_user.id
            result.bump("local users")
        await control_db.commit()
        for email, u in existing_users.items():
            user_id_by_email.setdefault(email, u.id)

    for entry in data.get("group_memberships", []):
        group_id = group_id_by_name.get(entry["group_name"])
        user_id = user_id_by_email.get(entry["user_email"])
        if group_id is None or user_id is None:
            result.warnings.append(f"Group membership '{entry['user_email']}' in '{entry['group_name']}' could not be resolved -- skipped.")
            continue
        existing = (
            await tenant_db.execute(select(GroupMembership).where(GroupMembership.group_id == group_id, GroupMembership.user_id == user_id))
        ).scalar_one_or_none()
        if existing is None:
            tenant_db.add(GroupMembership(group_id=group_id, user_id=user_id))
            result.bump("group memberships")
    await tenant_db.flush()

    webhook_id_by_name: dict[str, int] = {}
    for entry in data.get("webhooks", []):
        row, created = await _upsert_by_key(
            tenant_db,
            WebhookConfig,
            "name",
            entry["name"],
            {
                "url": entry.get("url", ""),
                "http_method": entry.get("http_method", "POST"),
                "headers": entry.get("headers") or {},
                "payload_template": entry.get("payload_template", "{}"),
                "timeout_seconds": entry.get("timeout_seconds", 10),
                "success_codes": entry.get("success_codes", "200,201,202,204"),
                "alert_on_failure": entry.get("alert_on_failure", False),
            },
        )
        webhook_id_by_name[entry["name"]] = row.id
        result.bump("webhooks" if created else "webhooks (updated)")
        if entry.get("headers_redacted"):
            result.warnings.append(f"Webhook '{entry['name']}': headers were redacted in the bundle -- re-enter them in Admin > Webhooks.")

    channel_id_by_name: dict[str, int] = {}
    for entry in data.get("notification_channels", []):
        cfg = entry.get("config") or {}
        if entry["channel_type"] == "webhook":
            webhook_id = webhook_id_by_name.get(cfg.get("webhook_name"))
            if webhook_id is None:
                result.warnings.append(
                    f"Notification channel '{entry['name']}': referenced webhook '{cfg.get('webhook_name')}' not found -- skipped."
                )
                continue
            resolved_config: dict = {"webhook_id": webhook_id}
        elif entry.get("config_redacted"):
            resolved_config = {}
        else:
            resolved_config = cfg
        row, created = await _upsert_by_key(
            tenant_db,
            NotificationChannel,
            "name",
            entry["name"],
            {
                "channel_type": entry["channel_type"],
                "is_enabled": entry.get("is_enabled", True),
                "message_template": entry.get("message_template", ""),
                "subject_template": entry.get("subject_template"),
            },
        )
        row.config_encrypted = encrypt_json(resolved_config)
        channel_id_by_name[entry["name"]] = row.id
        result.bump("notification channels" if created else "notification channels (updated)")
        if entry.get("config_redacted"):
            result.warnings.append(f"Notification channel '{entry['name']}': config was redacted in the bundle -- re-enter it in Admin > Notification Channels.")
    await tenant_db.flush()

    flow_id_by_name: dict[str, int] = {}
    for entry in data.get("approval_flows", []):
        row, created = await _upsert_by_key(
            tenant_db,
            ApprovalFlow,
            "name",
            entry["name"],
            {"is_default": entry.get("is_default", False), "notify_syslog_on_approval": entry.get("notify_syslog_on_approval", False)},
        )
        flow_id_by_name[entry["name"]] = row.id
        result.bump("approval flows" if created else "approval flows (updated)")

        await tenant_db.execute(delete(ApprovalFlowStep).where(ApprovalFlowStep.flow_id == row.id))
        steps = entry.get("steps", [])
        added_steps = 0
        for step in steps:
            group_id = group_id_by_name.get(step.get("approver_group_name")) if step.get("approver_group_name") else None
            user_id = user_id_by_email.get(step.get("approver_user_email")) if step.get("approver_user_email") else None
            if not group_id and not user_id:
                result.warnings.append(f"Approval flow '{entry['name']}' step '{step.get('label')}': no resolvable approver -- skipped.")
                continue
            tenant_db.add(
                ApprovalFlowStep(
                    flow_id=row.id, sort_order=step.get("sort_order", 0), label=step.get("label", ""), approver_group_id=group_id, approver_user_id=user_id
                )
            )
            added_steps += 1
        result.bump("approval flow steps", added_steps)
    await tenant_db.flush()

    for entry in data.get("event_policies", []):
        flow_name = entry.get("approval_flow_name")
        flow_id = flow_id_by_name.get(flow_name) if flow_name else None
        if flow_name and flow_id is None:
            result.warnings.append(f"Event policy '{entry['name']}': approval flow '{flow_name}' not found -- imported with no flow attached.")
        _, created = await _upsert_by_key(
            tenant_db,
            TicketRule,
            "name",
            entry["name"],
            {
                "is_active": entry.get("is_active", True),
                "promotion_type": entry.get("promotion_type", "single"),
                "ticket_type": entry.get("ticket_type", "incident"),
                "match_field": entry.get("match_field", "message"),
                "pattern": entry.get("pattern", ""),
                "title_template": entry.get("title_template", "{message}"),
                "severity": entry.get("severity", "medium"),
                "asset_match_field": entry.get("asset_match_field"),
                "sort_order": entry.get("sort_order", 0),
                "group_by": entry.get("group_by", "none"),
                "window_minutes": entry.get("window_minutes", 5),
                "ml_score_threshold": entry.get("ml_score_threshold", 0.7),
                "ml_warmup_count": entry.get("ml_warmup_count", 250),
                "ml_algorithm": entry.get("ml_algorithm", "half_space_trees"),
                "ml_sidecar_enabled": entry.get("ml_sidecar_enabled", False),
                "approval_flow_id": flow_id,
            },
        )
        result.bump("event policies" if created else "event policies (updated)")

    for entry in data.get("platform_response_rules", []):
        row, created = await _upsert_by_key(
            tenant_db,
            PlatformEventRule,
            "name",
            entry["name"],
            {
                "is_active": entry.get("is_active", True),
                "trigger_event": entry.get("trigger_event", "incident_created"),
                "match_field": entry.get("match_field", "title"),
                "pattern": entry.get("pattern", ""),
                "sort_order": entry.get("sort_order", 0),
                "created_by": updated_by,
            },
        )
        result.bump("platform response rules" if created else "platform response rules (updated)")

        await tenant_db.execute(delete(PlatformEventAction).where(PlatformEventAction.rule_id == row.id))
        added_actions = 0
        for action in entry.get("actions", []):
            action_type = action.get("action_type")
            config: dict = {}
            if action_type in ("notify_slack", "notify_email"):
                channel_id = channel_id_by_name.get(action.get("channel_name"))
                if channel_id is None:
                    result.warnings.append(
                        f"Platform Response Rule '{entry['name']}': action '{action_type}' references channel "
                        f"'{action.get('channel_name')}', not found here -- skipped."
                    )
                    continue
                config = {"channel_id": channel_id}
            elif action_type == "webhook":
                webhook_id = webhook_id_by_name.get(action.get("webhook_name"))
                if webhook_id is None:
                    result.warnings.append(
                        f"Platform Response Rule '{entry['name']}': action 'webhook' references webhook "
                        f"'{action.get('webhook_name')}', not found here -- skipped."
                    )
                    continue
                config = {"webhook_id": webhook_id}
            elif action_type == "add_watcher":
                config = {"email": action.get("email", "")}
            elif action_type == "mark_problematic":
                config = {}
            else:
                config = action.get("config") or {}
            tenant_db.add(PlatformEventAction(rule_id=row.id, action_type=action_type, config=config))
            added_actions += 1
        result.bump("platform response rule actions", added_actions)

    for entry in data.get("service_catalog", []):
        flow_name = entry.get("approval_flow_name")
        flow_id = flow_id_by_name.get(flow_name) if flow_name else None
        if flow_name and flow_id is None:
            result.warnings.append(f"Service Catalog item '{entry['name']}': approval flow '{flow_name}' not found -- imported with no flow attached.")
        row, created = await _upsert_by_key(
            tenant_db,
            ServiceCatalogItem,
            "key",
            entry["key"],
            {
                "name": entry.get("name", entry["key"]),
                "description": entry.get("description"),
                "icon": entry.get("icon"),
                "ticket_type": entry.get("ticket_type", "incident"),
                "default_severity": entry.get("default_severity", "medium"),
                "payload_format": entry.get("payload_format", "json"),
                "requires_approval": entry.get("requires_approval", False),
                "approval_flow_id": flow_id,
                "is_active": entry.get("is_active", True),
                "sort_order": entry.get("sort_order", 0),
            },
        )
        result.bump("service catalog items" if created else "service catalog items (updated)")

        await tenant_db.execute(delete(ServiceCatalogField).where(ServiceCatalogField.catalog_item_id == row.id))
        fields = entry.get("fields", [])
        for f in fields:
            tenant_db.add(
                ServiceCatalogField(
                    catalog_item_id=row.id,
                    field_key=f["field_key"],
                    label=f.get("label", f["field_key"]),
                    field_type=f.get("field_type", "text"),
                    select_options=f.get("select_options"),
                    is_required=f.get("is_required", False),
                    sort_order=f.get("sort_order", 0),
                    source_mode=f.get("source_mode"),
                    source_expression=f.get("source_expression"),
                )
            )
        result.bump("service catalog fields", len(fields))

    await tenant_db.commit()
    return result
