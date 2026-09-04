# RAIN and EUCS: a scope-honest assessment

What RAIN can and cannot do for an organization pursuing the EU
Cybersecurity Certification Scheme for Cloud Services (EUCS). Shorter
and narrower than [`docs/itsm-controls-mapping.md`](itsm-controls-mapping.md)
because EUCS is a narrower, differently-shaped framework than FedRAMP
or ISO 27001.

## What EUCS is

A candidate certification scheme from ENISA under the EU Cybersecurity
Act (Regulation (EU) 2019/881). As of this writing it has circulated in
multiple drafts since 2020 and has not been formally adopted -- "EUCS
compliance" today means working from a draft, and the control catalog
can still change. This document evaluates RAIN against the scheme's
stable structure (assurance levels, control domains) rather than
specific control IDs.

Three assurance levels: Basic, Substantial, High. The control catalog
is built on the German BSI C5 catalogue and cross-references ISO/IEC
27001 and the CSA Cloud Controls Matrix. Domains include Organisation
of Information Security, Risk Management, Asset Management, Physical
Security, Operational Security, Identity and Access Management,
Cryptography and Key Management, Change and Configuration Management,
Incident Management, Business Continuity, Compliance, and (High
assurance only) a CSP's exposure to non-EU legal jurisdiction.

EUCS certifies cloud service providers and their services, not software
an organization runs for itself. RAIN is self-hosted and is never the
thing being certified. Running RAIN does not make an organization or
its cloud service EUCS-compliant -- at most it's evidence-generating
infrastructure a CSP can use toward its own control implementation,
which is what the table below evaluates.

## Domain-by-domain fit

**Direct**: RAIN's own record-keeping is the artifact an assessor would
look at. **Partial**: RAIN holds supporting evidence but the control is
substantially about something RAIN doesn't do. **None**: outside
anything a ticketing/document/asset system addresses.

| EUCS domain | Fit | Notes |
|---|---|---|
| Asset Management | Direct | No-code asset types, custom fields, CSV/JSON/Excel import and export -- the CMDB an assessor would sample. |
| Change and Configuration Management | Direct | Change tickets with approval steps, timestamps, and an audit trail. |
| Incident Management | Direct | Incident tickets with full timelines, Event Promotion Policies, root-cause assistance. |
| Operational Security | Partial | RAIN records the tickets operational procedures produce, but doesn't patch, monitor, or scan -- detection is bring-your-own by design. |
| Human Resources | Partial | `last_login_at` per user, exportable as CSV, identifies dormant accounts to deactivate. Background checks, training records, and HR policy stay outside RAIN. |
| Compliance | Partial | Document repository with tags, PDF export, and a shareable Trust Center view; per-document review-due dates and assignable read-acknowledgment (emailed, tracked pending, visible in the client portal until acknowledged). RAIN doesn't generate compliance judgments or run assessments. |
| Identity and Access Management | Partial | RAIN's own RBAC, local auth, LDAP/AD, SAML SSO, and dormant-account detection cover access to RAIN itself, not the CSP's cloud service or customer-facing IAM. |
| Business Continuity | Partial | Ticket/document history can evidence a BC exercise happened, including a review-due date on the BC plan itself. RAIN provides no backup, DR, or failover capability. |
| Organisation of Information Security | Partial | Document repository holds and versions policy; review-due dates and staff acknowledgment are direct evidence of periodic review and attestation. Doesn't define or enforce a security organization. |
| Risk Management | Partial | A starter Risk Register template (`docs/compliance-templates/`) seeds likelihood/impact/treatment/review-date fields. No dedicated risk-scoring engine. |
| Cryptography and Key Management | None | RAIN uses TLS and standard at-rest protections for its own data; no key management or HSM integration for a CSP's service. |
| Physical Security | None | A matter of the CSP's data center controls. |
| Communication Security | None | RAIN doesn't operate or configure the CSP's network. |
| Portability and Interoperability | None | Concerns the CSP's cloud service offering, not RAIN. |
| Development of Information Systems | None outside change tracking | Change tickets can evidence code review happened; no involvement in SDLC, CI/CD, or secure coding practices. |
| Procurement Management | Partial | A starter Subprocessor Register template tracks vendors, data processed, hosting region, contract/DPA review dates. Still a contractual matter RAIN doesn't manage end to end. |
| User Documentation | Partial | Document repository, PDF export, and Trust Center are a place to publish user-facing documentation; authoring it is the organization's work. |
| Government Investigation Requests | Partial | Intake/legal-review/sign-off is a tracked-approval workflow (the same shape a Service Catalog item with an approval flow gives a Change ticket). Gap: no per-ticket visibility restriction -- any signed-in tenant user can read any ticket, so confidentiality depends on the whole tenant's user base, not just Legal. |

## The High-assurance sovereignty question

Draft EUCS at High assurance has included provisions on a CSP's
exposure to legal access requests from non-EU governments (the
scheme's "immunity"/"sovereignty" requirements) -- the most contested
part of the draft, and not settled as of this writing.

This is a question of corporate structure, ownership, and hosting
jurisdiction, not something a software tool resolves. Worth noting only
because RAIN's own deployment happens to be compatible with any answer:
self-hosted, no external service dependency, runs fully air-gapped.
That's a fact about RAIN's deployment model, not a claim that RAIN
satisfies the sovereignty requirement itself, which is decided by where
and how the CSP's actual cloud service runs.

## Bottom line

RAIN is a credible source of change, incident, and asset evidence for
the domains a ticketing/CMDB system can realistically speak to: Asset
Management, Change and Configuration Management, Incident Management,
with partial support elsewhere in the table above. It has nothing to
offer domains specific to running a cloud service: Cryptography and Key
Management, Physical Security, Communication Security, Portability and
Interoperability. Those need purpose-built controls regardless of which
ITSM tool is in use.

Use RAIN as the record-keeping layer under a subset of an EUCS control
implementation, not as a compliance product in its own right. No part
of RAIN is EUCS-certified, and self-hosting it does not make an
organization's cloud service EUCS-compliant.

*Based on EUCS draft materials publicly circulated by ENISA. Not legal
or certification advice. EUCS has not been formally adopted as an
implementing act as of this writing -- confirm current status and exact
control text with ENISA or your national cybersecurity authority before
relying on this document.*
