# RAIN and EUCS: a scope-honest assessment

This document evaluates what RAIN can and cannot do for an organization
pursuing the EU Cybersecurity Certification Scheme for Cloud Services
(EUCS). It is deliberately shorter and narrower than
[`docs/itsm-controls-mapping.md`](itsm-controls-mapping.md), because EUCS
is a narrower, differently-shaped framework than FedRAMP or ISO 27001,
and overstating the fit would be more misleading than useful.

## What EUCS actually is

EUCS is a candidate certification scheme developed by ENISA under the EU
Cybersecurity Act (Regulation (EU) 2019/881). As of this document's
writing it has circulated in multiple draft versions since 2020 but has
not been formally adopted as an implementing act; organizations citing
"EUCS compliance" today are working from a draft, not a finalized legal
text, and the exact control catalog is still subject to change. This
document therefore evaluates RAIN against the scheme's stable structural
elements (its assurance levels and control domains, which have been
consistent across drafts) rather than against specific control IDs,
which have not been.

EUCS defines three assurance levels: Basic, Substantial, and High,
mirroring the general assurance-level structure the Cybersecurity Act
uses across all its certification schemes. Its control catalog is built
directly on the German BSI Cloud Computing Compliance Criteria Catalogue
(C5) and cross-references ISO/IEC 27001 and the CSA Cloud Controls
Matrix. The scheme organizes controls into domains such as Organisation
of Information Security, Risk Management, Asset Management, Physical
Security, Operational Security, Identity and Access Management,
Cryptography and Key Management, Change and Configuration Management,
Incident Management, Business Continuity, Compliance, and (at High
assurance specifically) provisions addressing a cloud provider's
exposure to non-EU legal jurisdiction.

## The scope mismatch that has to be stated up front

EUCS certifies **cloud service providers** and the **cloud services**
they offer to customers. It is not a scheme for evaluating software
that an organization runs for its own internal use. RAIN is
self-hosted: an organization deploys it on infrastructure it already
controls, and RAIN itself is never the thing being certified.

This means there are exactly two situations where RAIN is relevant to
an EUCS engagement, and they are different questions:

1. **The organization running RAIN is itself a cloud service provider
   pursuing EUCS for a service it offers.** In this case RAIN is
   internal tooling, the same as a ticketing system, CMDB, or document
   repository would be for any other framework. It can generate and
   hold evidence supporting a subset of the operational domains below.
   It does not itself need to be certified, any more than an
   organization's ticketing system needs to be FedRAMP-authorized for
   the organization to hold a FedRAMP authorization.

2. **The organization running RAIN is a customer of a certified cloud
   provider and wants RAIN to help manage its own side of that
   relationship** (tracking the provider's SLAs, incidents, and
   contractual obligations as tickets and documents). This is a
   legitimate but much smaller use case than (1), and is not addressed
   further in this document beyond noting that RAIN's generic
   ticket/document/asset model handles it the same way it handles any
   vendor-management workflow, with no EUCS-specific features involved.

Nothing below should be read as "RAIN is EUCS-compliant" or "RAIN helps
you get EUCS-certified." RAIN is evidence-generating infrastructure that
a CSP could use as part of its own control implementation. The
certification itself is assessed against the CSP's people, processes,
and cloud service, not against RAIN.

## Domain-by-domain fit

Evaluated against the CSP-uses-RAIN-internally scenario above. "Direct"
means RAIN's own record-keeping is the artifact an assessor would look
at. "Partial" means RAIN can hold supporting evidence but the control is
substantially about something RAIN doesn't do. "None" means the control
is outside anything a ticketing/document/asset system addresses.

| EUCS domain | Fit | Notes |
|---|---|---|
| Asset Management | Direct | No-code asset types, custom fields, CSV/JSON/Excel import and export; the CMDB-equivalent an assessor would sample. |
| Change and Configuration Management | Direct | Change tickets with approval steps, timestamps, and an audit trail; the same evidence class FedRAMP change-management controls rely on. |
| Incident Management | Direct | Incident tickets with full timelines, Event Promotion Policies turning syslog events into tickets, root-cause assistance surfacing repeat patterns. |
| Operational Security | Partial | RAIN records the *tickets* that operational procedures produce (patching, monitoring follow-up, vulnerability tickets) but doesn't perform patching, monitoring, or vulnerability scanning itself; it is "bring your own" detection by design. |
| Human Resources | Partial | Access-review evidence for account deprovisioning: `last_login_at` on every platform user, exported as a CSV, identifies dormant accounts that should be deactivated. Background checks, training records, and HR policy itself stay outside RAIN entirely. |
| Compliance | Partial | Document repository with tags, PDF export, and a shareable "Trust Center" view holds and presents policy documents and audit artifacts; a per-document review-due date and flag, plus an assignable "requires acknowledgment from" a person or group (emailed when set, tracked as pending until each of them clicks "I have read this," shown in the client portal until they do), evidence that policies are reviewed on a cadence and actually read by the specific staff required to. RAIN still doesn't generate compliance judgments or run assessments itself. |
| Identity and Access Management | Partial | RAIN's own RBAC, local auth, LDAP/AD, SAML 2.0 SSO, and now `last_login_at`-based dormant-account detection are relevant only to access to RAIN itself, not to the CSP's cloud service or its customer-facing IAM, which is what EUCS's IAM domain actually assesses. |
| Business Continuity | Partial | Ticket/document history can evidence that a BC exercise happened and was tracked, including via a document's own review-due date for the BC plan itself; RAIN provides no backup, DR, or failover capability of its own and isn't part of the recovery path it would be documenting. |
| Organisation of Information Security / Information Security Policies | Partial | The document repository holds and versions policy documents; each document's optional review-due date and assignable acknowledgment requirement (who must read it, tracked as pending, emailed on request) are direct evidence for the periodic-review and staff-attestation requirements this domain leans on -- not just that someone eventually read it, but that the specific people required to did. Doesn't define or enforce a security organization on its own. |
| Risk Management | Partial | A starter Risk Register bundle template (docs/compliance-templates/) seeds a custom asset type with likelihood/impact/treatment/review-date fields, so a risk register is a five-minute import rather than a from-scratch build. RAIN still has no dedicated risk-assessment methodology or scoring engine. |
| Cryptography and Key Management | None | RAIN uses TLS (via Caddy) and standard at-rest protections for its own data, but provides no key management, HSM integration, or cryptographic control surface for a CSP's service. |
| Physical Security | None | Not applicable to any software system; entirely a matter of the CSP's data center controls. |
| Communication Security | None | RAIN doesn't operate or configure the CSP's network; its own network exposure (Caddy, Postgres, syslog listener) is an input to the CSP's own CS controls, not a substitute for them. |
| Portability and Interoperability | None | Concerns the CSP's cloud service offering, not RAIN. |
| Development of Information Systems | None outside change tracking | RAIN's change tickets can evidence that code changes went through review, but RAIN has no involvement in the CSP's actual SDLC, CI/CD, or secure coding practices. |
| Procurement Management | Partial | A starter Subprocessor Register bundle template (docs/compliance-templates/) seeds a custom asset type for tracking vendors, data processed, hosting region, and contract/DPA review dates. Still a contractual and organizational matter RAIN doesn't manage end to end. |
| User Documentation | Partial | The document repository, PDF export, and Trust Center portal are a reasonable place to publish EUCS-required user-facing documentation, but authoring that documentation is the organization's work, not RAIN's. |
| Dealing with Investigation Requests from Government Agencies | None | A legal and jurisdictional matter for the CSP's own counsel and corporate structure, not something a ticketing system participates in. |

## The High-assurance sovereignty question

Draft versions of EUCS at the High assurance level have included
provisions addressing a CSP's exposure to legal access requests from
non-EU governments (commonly discussed as the scheme's "immunity" or
"sovereignty" requirements). This has been the most contested part of
the draft scheme and its final form, if any, was not settled as of this
writing.

This question is about corporate structure, ownership, and hosting
jurisdiction. It is not something a software tool resolves. It is worth
noting only because RAIN's own architecture happens to be compatible
with whatever answer an organization needs here: RAIN is self-hosted,
has no external service dependency, phones home to nothing, and runs
correctly fully air-gapped. Running RAIN doesn't introduce a foreign
dependency into a CSP's stack the way a SaaS ticketing tool would. That
is a fact about RAIN's deployment model, not a claim that RAIN satisfies
or contributes to the sovereignty requirement itself, which is decided
by where and how the CSP's actual cloud service runs.

## Bottom line

RAIN is a credible source of change, incident, and asset evidence for
the small number of EUCS operational domains that a ticketing/CMDB
system can realistically speak to: Asset Management, Change and
Configuration Management, and Incident Management, with partial support
for Compliance documentation, Human Resources access review, Risk
Management, Procurement Management, and Business Continuity
record-keeping. It has nothing to offer the domains that are actually
specific to running a cloud service: Cryptography and Key Management,
Physical Security, Communication Security, Portability and
Interoperability, and Dealing with Investigation Requests. An
organization pursuing EUCS needs purpose-built controls and evidence for
those domains regardless of which ITSM tool it runs.

Use RAIN, if at all, as the record-keeping layer under a subset of an
EUCS control implementation, not as a compliance product in its own
right. No part of RAIN is EUCS-certified, and self-hosting it does not
make an organization's cloud service EUCS-compliant.

*This assessment is based on EUCS draft materials publicly circulated by
ENISA and does not constitute legal or certification advice. EUCS has
not been formally adopted as an implementing act as of this writing;
organizations pursuing certification should confirm the current status
and exact control text with ENISA or their national cybersecurity
authority before relying on this document.*
