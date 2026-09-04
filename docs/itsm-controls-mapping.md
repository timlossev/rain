# Controls Requiring IT Service Management Practices

> Maps compliance controls -- FedRAMP/NIST 800-53 and a dozen other
> frameworks -- to the specific ITSM capability that satisfies them: a
> change ticket, an incident record, a CMDB entry, an access-approval
> workflow. In a real FedRAMP High authorization package, 33 of 409
> implemented controls require a structured system of record as the
> only credible way to produce evidence an assessor accepts. Run RAIN
> as your ticketing/asset/document system of record and you generate
> that evidence by using it day to day.

---

## Why a System of Record, Not a Policy Document

NIST SP 800-53 (Rev 5) defines what outcome a control requires, not how
to implement it. For controls about authorization, tracking, and
accountability, the only mechanism that generates acceptable evidence
at scale is a system of record: a ticket, a CMDB entry, an approval
chain.

FedRAMP is the reference dataset here because it has rigorously
assessed, public, itemized control language -- not because the finding
is FedRAMP-specific (see Cross-Framework Applicability below). The
reference package: a real FedRAMP High authorization, 409 implemented
controls and enhancements across 18 families.

---

## ITSM Coverage Analysis

Of 409 controls in this reference implementation, 33 have
implementation statements that explicitly require a structured system
of record -- ticketing, CMDB, or workflow-driven approval.

| Metric | Count | % of Package |
|---|---|---|
| Total controls/enhancements in package | 409 | 100% |
| Controls requiring a system of record | 33 | ~8% |
| Controls where ITSM is the *primary* mechanism | 22 | ~5.4% |
| Controls where ITSM is a *supporting* mechanism | 11 | ~2.7% |

These 33 concentrate in the families that get the most 3PAO scrutiny:
Configuration Management, Incident Response, Access Control. A finding
in any of them can produce a POA&M that delays or conditions the ATO.

### ITSM Controls by Family

| Family | ITSM Controls | Count | % of Family |
|---|---|---|---|
| CM -- Configuration Management | CM-2, CM-2(2), CM-3, CM-3(1), CM-3(2), CM-8, CM-8(2), CM-9 | 8 | 24% |
| IR -- Incident Response | IR-4, IR-5, IR-5(1), IR-7, IR-7(1) | 5 | 21% |
| AC -- Access Control | AC-2, AC-3, AC-4, AC-6(5), AC-6(7) | 5 | 10% |
| MA -- Maintenance | MA-2, MA-5, MA-5(1) | 3 | 25% |
| AU -- Audit and Accountability | AU-5, AU-5(2), AU-12(3) | 3 | 11% |
| PS -- Personnel Security | PS-4, PS-4(2), PS-5 | 3 | 27% |
| SI -- System and Information Integrity | SI-2, SI-5, SI-6 | 3 | 9% |
| SA -- System and Services Acquisition | SA-10, SA-4(9) | 2 | 8% |
| SC -- System and Communications Protection | SC-7(4) | 1 | 3% |

MA and PS have the highest proportional dependency -- over a quarter of
each family's controls need structured records. CM has the highest
absolute count.

---

## The Controls

### Change Tickets / Change Advisory Board (CAB / TRB)

A change ticket is the only practical mechanism that enforces a
formal, multi-person approval chain at scale.

| Control | Title | Why a ticket is required |
|---|---|---|
| CM-3 | Configuration Change Control | Ties requester, approver, implementer, test evidence, and disposition into one traceable record. |
| CM-3(1) | Automated Documentation, Notification, and Prohibition of Changes | A workflow-driven ticket can't close without required sign-offs and notifies at each transition. |
| CM-3(2) | Testing, Validation, and Documentation of Changes | Attached test results and impact assessments prove the change wasn't deployed before testing completed. |
| CM-2 | Baseline Configuration | The approval trail proves the baseline was only changed with authorization. |
| CM-2(2) | Automation Support for Accuracy and Currency | The ticket record stamps who requested, reviewed, approved, and implemented, and when. |
| CM-9 | Configuration Management Plan | Structured change requests plus a CI inventory show the plan is followed, not just written. |
| SA-10 | Developer Configuration Management | Routing developer changes through a CAB ticket treats code/schema/deploy config as managed CIs with review and audit trail. |
| SA-4(9) | Functions, Ports, Protocols, and Services in Use | TRB approval via ticket ensures no new port or service opens without security review. |
| SC-7(4) | External Telecommunications Services (Boundary Protection) | Traffic exceptions need CAB approval before the firewall rule exists; periodic-review findings become remediation tickets. |
| AU-12(3) | Changes by Authorized Individuals | A TRB-approved ticket stops audit-scope reduction without a formal, multi-person review. |
| SI-2 | Flaw Remediation | Scanner findings become time-bound remediation tickets, CAB-approved before production patching. |

### CMDB / Configuration Items

| Control | Title | Why a CMDB is required |
|---|---|---|
| CM-8 | System Component Inventory | The CMDB is the authoritative record of component identity, relationships, ownership, and status. |
| CM-8(2) | Automated Maintenance | Automated discovery feeding the CMDB, with discrepancy alerts, operationalizes "detect unauthorized components." |
| CM-9 | Configuration Management Plan | The CMDB is the registry that makes formal CI management operational. |

### Incident Tickets

| Control | Title | Why a ticket is required |
|---|---|---|
| IR-4 | Incident Handling | One record tracks detection through closure, with timestamps and chain-of-custody evidence. |
| IR-5 | Incident Monitoring | "Track and document" is what an incident ticket provides: status, priority, owner, resolution notes, timestamps. |
| IR-5(1) | Automated Tracking, Data Collection, and Analysis | SIEM-to-ticketing integration auto-generates records and enables trend/SLA analysis. |
| IR-7 | Incident Response Assistance | NIST's own guidance names automated ticketing as a canonical support resource. |
| IR-7(1) | Automation Support for Availability of Information and Support | Automated ticket creation with SLA escalation means no incident stalls waiting for a human to notice. |

### Access Request Tickets / Approval Workflows

| Control | Title | Why a ticket is required |
|---|---|---|
| AC-2 | Account Management | The ticket captures requester, justification, approver, and date -- proof each action was sanctioned. |
| AC-3 | Access Enforcement | Requester → approver → implementer, documented, proves enforcement rather than policy alone. |
| AC-4 | Information Flow Enforcement | A change ticket through the approval board reviews every firewall exception before implementation. |
| AC-6(5) | Privileged Accounts | Per-account justification and owner approval gives reviewers a least-privilege evidence trail. |
| AC-6(7) | Review of User Privileges | A remediation ticket with a due date ensures a review finding is actually acted on. |

### Maintenance Tickets

| Control | Title | Why a ticket is required |
|---|---|---|
| MA-2 | Controlled Maintenance | The ticket records what was done, by whom, and under what approval -- distinguishing controlled from unplanned work. |
| MA-5 | Maintenance Personnel | The ticket records who was given access, who escorted them, and when access was terminated. |
| MA-5(1) | Individuals Without Appropriate Access | Closure review confirms escort, sanitization, and access revocation all happened. |

### Audit and Accountability Tickets

| Control | Title | Why a ticket is required |
|---|---|---|
| AU-5 | Response to Audit Logging Process Failures | An auto-generated, SLA-bound ticket forces and evidences a response. |
| AU-5(2) | Real-time Alerts | Alert-to-ticket routing requires a human to close it, proving the alert was acted on. |
| AU-12(3) | Changes by Authorized Individuals | *(See Change Tickets above -- also an audit control.)* |

### Personnel Workflow Tickets

| Control | Title | Why a ticket is required |
|---|---|---|
| PS-4 | Personnel Termination | A parent off-boarding record with per-team child tasks makes every access point verifiably revoked. |
| PS-4(2) | Automated Actions | Automated off-boarding notifies distribution lists and creates a deadlined task, removing human-dependency lag. |
| PS-5 | Personnel Transfer | A structured transfer ticket revokes and reprovisions access with the same rigor as a hire or termination. |

### System Integrity Tickets

| Control | Title | Why a ticket is required |
|---|---|---|
| SI-2 | Flaw Remediation | *(See Change Tickets above -- also an integrity control.)* |
| SI-5 | Security Alerts, Advisories, and Directives | A ticket per advisory proves each one got reviewed, not silently ignored. |
| SI-6 | Security Function Verification | A ticket assigns corrective work with a deadline when a verification failure (e.g. an AV gap) is found. |

---

## Summary

| ITSM Capability | Controls Dependent | Without It |
|---|---|---|
| Change tickets with CAB/TRB approval | 11 | Findings on CM-3, SI-2, AC-4, SA-10 |
| CMDB / Configuration item registry | 3 | Findings on CM-8, CM-9 |
| Incident tickets with lifecycle tracking | 5 | Findings on IR-4, IR-5, IR-7 |
| Access request tickets with approval chain | 5 | Findings on AC-2, AC-3, AC-6 |
| Maintenance records with escort/work detail | 3 | Findings on MA-2, MA-5 |
| Alert-to-ticket automation | 2 | Findings on AU-5 |
| Personnel workflow tickets (on/off-boarding) | 3 | Findings on PS-4, PS-5 |

FedRAMP High 3PAOs don't accept verbal attestation or policy
references for these controls -- they require ticket numbers,
timestamps, approval records, closure notes, trend data. A structured
ITSM platform generates those artifacts continuously, which is the
difference between a clean assessment and a POA&M backlog.

---

## Moderate and Low Baselines

The 33-control figure is specific to this High package but not a
High-specific dependency: 19 of 33 are base controls, which survive
into the smaller baselines even as enhancements drop away. The same
roughly-one-in-ten proportion holds at Moderate and Low.

## Native Mechanisms Added Since This Analysis

This is a single SSP-snapshot analysis, not re-run since. Three
controls that used to sit in Indirect Coverage below have since gained
a dedicated mechanism instead of relying on judgment:

- AC-2(3) (Disable Accounts) -- `last_login_at`, a dedicated column
  stamped on every sign-in, exportable straight to CSV from Admin >
  Users.
- PL-4 (Rules of Behavior) / PS-6 (Access Agreements) -- a document's
  "Requires acknowledgment from" is a dedicated feature: tracked
  pending state, client-portal surfacing, automatic email, Platform
  Response Rule trigger.
- PL-2 (System Security Plan), supporting tier -- a document's
  review-due date is a dedicated field with an overdue flag and
  filter.

That's a real promotion into the same category the 33 already uses.
What it isn't is a re-stated 37/409 headline: the 33 was counted
control-by-control against one reference package's actual
implementation-statement language, and a defensible new total needs
that same source material and methodology.

## Indirect Coverage

A second set of controls, outside the 33, aren't ticket-shaped by
nature but can use RAIN's ticket/document/calendar primitives as their
evidence mechanism with some implementation judgment. Several also have
ready-to-import starter templates under
[`docs/compliance-templates/`](compliance-templates/) -- a template
lowers setup cost, it doesn't change a control's classification here.

- **CA-5 (POA&M)** -- a POA&M item is structurally a ticket (finding,
  owner, due date, closure); the strongest indirect fit. The
  `poam-tracking-fields.rain` template adds FedRAMP-specific ticket
  fields (POA&M ID, finding source, CVE/finding ID, original risk
  rating, scheduled completion date, POC, deviation type). Gap: no
  first-class milestone list -- the ticket's comment thread and status
  history substitute for FedRAMP's discrete dated milestones, not a
  literal replacement. Under FedRAMP's 2026 Consolidated Rules (CR26,
  required-to-maintain January 1 2027), the monthly POA&M is being
  superseded by a quarterly Ongoing Certification Report (OCR); POA&Ms
  become primarily agency-owned rather than disappearing. The
  `fedramp-ocr-fields.rain` template covers OCR content (accepted
  vulnerabilities, reportable incidents, transformative changes)
  alongside, not instead of, the POA&M template.
- **RA-5 / RA-7 (Vulnerability Scanning / Risk Response)** -- RAIN is
  the remediation-tracking half, not the scanner. Tickets > Import
  accepts a `.nessus` scan export directly, turning every non-Info
  finding into a vulnerability ticket with no manual mapping. The
  `nessus-finding-fields.rain` template adds scanner metadata (plugin
  ID, CVSS, port/protocol, risk factor) as filterable fields. The
  importer's "Dedup key" (`Ticket.external_finding_key`) makes a
  recurring re-scan safe to re-import: an open match is left alone, a
  closed match is reopened and flagged recurring instead of duplicated.
- **RA-3 (Risk Assessment)** -- `risk-register.rain` turns this into a
  five-minute import instead of a from-scratch asset type.
- **CP-4, PE-3/PE-6, SR-2/SR-6, MP-6** (Contingency Testing, Physical/
  Visitor Access, Supply Chain Reviews, Media Sanitization) -- each
  loggable as a ticket or recurring calendar entry, same pattern as
  MA-5(1)'s escort/sanitization tracking. SR-2/SR-6 also has
  `subprocessor-register.rain`.
- **IA-2 / PE-2, with a PS-3 assist** -- `piv-cac-card-issuance.rain`
  tracks the credential (serial/FASC-N, card type, issuing agency,
  issue/expiration, status), sponsoring official, and background
  investigation tier.
- **CM-10 (Software Usage Restrictions)** --
  `software-license-register.rain` tracks vendor, license type, seat
  count, renewal date, status -- the licensing half CM-8 doesn't cover.
- **CM-8(3) / SI-7** -- a document populated from a scheduled
  infrastructure-discovery run alerts on the first snapshot diff (see
  [`docs/drift-detection.md`](drift-detection.md)). Detects the
  *undocumented* change: the verification half CM-2's baseline and
  CM-3's approval trail don't provide alone. `cloud-environment-register.rain`
  tracks the account/environment this applies to.
- **SC-12 / SC-13** -- `encryption-key-cert-register.rain` tracks
  lifecycle (issued/expiration, algorithm, issuer, rotation owner,
  status) of managed keys and certs. Holds no key material, just the
  inventory a rotation/expiry review needs.
- **CA-3 (System Interconnections)** --
  `system-interconnection-register.rain` tracks each connection, its
  authorization/review dates, and status; the ISA itself links in as a
  Document.
- **PS-7 (Third-Party Personnel Security)** --
  `contractor-access-register.rain` tracks the individual (distinct
  from the Subprocessor Register's company level): sponsor, access
  level, background-check status, engagement dates.
- **RA-2 (Security Categorization)** -- `data-inventory-register.rain`
  tracks category, classification, owner, and retention per data
  holding -- a basic inventory, not full data-flow mapping.

---

## Cross-Framework Applicability

Change tickets, incident records, CMDB, access workflows, and
personnel lifecycle tracking are not artifacts of U.S. federal policy
-- the same requirement for a system of record recurs, worded
differently, across every major security/compliance framework
worldwide.

### European Union

**Germany -- BSI IT-Grundschutz** (mandatory for federal agencies,
widely adopted by critical infrastructure and finance):

| ITSM Practice | IT-Grundschutz Equivalent |
|---|---|
| Change tickets / CAB approval | OPS.1.1.3 -- documented change requests, impact assessment, approval before implementation |
| CMDB / Asset inventory | ORP.4 + SYS modules -- maintained inventories of systems and components |
| Incident tickets | DER.2.1 -- systematic detection, reporting, tracking through a defined process |
| Access request workflows | ORP.4 -- formal provisioning/revocation with documented authorization |
| Personnel lifecycle tickets | ORP.2 -- documented on/transfer/off-boarding with tracked revocation |

**France -- ANSSI SecNumCloud** (CSP qualification, roughly FedRAMP
High) and RGS (public-administration baseline):

| ITSM Practice | ANSSI Equivalent |
|---|---|
| Change tickets / CAB | SecNumCloud §10 -- formal change process, traceable request to closure |
| Incident tickets | SecNumCloud §13 -- ticketed lifecycle with escalation and reporting timelines |
| CMDB | SecNumCloud §8 -- continuously maintained asset inventory |
| Access workflows | SecNumCloud §9 -- documented provisioning/revocation with approval records |

SecNumCloud qualification requires third-party audit; a policy
described but not operationally evidenced doesn't pass.

**Netherlands -- BIO** (mandatory across Dutch public administration,
based on ISO/IEC 27001/27002):

| ITSM Practice | BIO / ISO 27002:2022 Equivalent |
|---|---|
| Change tickets / CAB | §8.32 -- formal request, risk assessment, approval, post-implementation review |
| CMDB | §5.9 -- maintained, accurate asset inventory |
| Incident tickets | §5.26 -- documented response with containment/eradication/recovery evidence |
| Access workflows | §5.18 -- formal provisioning, review, revocation with authorization |
| Personnel lifecycle | §6.5 -- timely, documented revocation on departure or role change |

Because BIO maps to ISO 27001, an ISO 27001-certified organization
satisfies BIO simultaneously.

**Spain -- ENS** (mandatory for public administration and CSPs
processing public data; three levels: Basic, Medium, High):

| ITSM Practice | ENS Equivalent |
|---|---|
| Change tickets / CAB | op.exp.5 -- formal documentation, approval, traceability |
| Incident tickets | op.exp.7 -- systematic recording, classification, tracking |
| CMDB | op.inv.1 -- current, accurate asset inventory |
| Access workflows | op.acc.4 -- documented provisioning/revocation with audit trail |
| Personnel lifecycle | mp.per.3 -- documented credential/access revocation on departure |

At ENS High, assessors require evidence artifacts, not policy
declarations.

**Poland -- KSC Act** (implementing the EU NIS Directive; references
ISO/IEC 27001 and NIST CSF):

| ITSM Practice | KSC / NIS2 Equivalent |
|---|---|
| Incident tickets | Art. 8 -- detection, handling, reporting to the national CSIRT within defined timeframes |
| Change tickets | ISO 27001 Annex A 8.32 (as referenced by KSC) |
| CMDB | Art. 8(1)(b) -- identification and management of systems/assets in scope |
| Access workflows | Art. 8(1)(d) -- documented authorization and revocation |

NIS2 (2022/2555), which EU member states must implement, requires
incident handling, business continuity, supply chain security, and
access control with evidence of implementation -- fines up to €10M or
2% of global turnover for non-compliance.

### Canada

**Government of Canada -- ITSG-33 / GC PBMM**, derived directly from
NIST 800-53:

| ITSM Practice | ITSG-33 / GC Equivalent |
|---|---|
| Change tickets / CAB | CM-3 (inherited) |
| CMDB | CM-8 (inherited) |
| Incident tickets | IR-4, IR-5 (inherited) |
| Access workflows | AC-2, AC-3 (inherited) |
| Personnel lifecycle | PS-4, PS-5 (inherited) |

An organization already ITSM-compliant for FedRAMP effectively
satisfies the equivalent Canadian federal requirements with the same
tooling. OSFI Guideline B-13 additionally requires federally regulated
financial institutions to maintain the same three categories --
change management, incident management with response timelines, asset
inventories -- with artifact evidence, not narrative.

### Asia-Pacific

**Singapore -- MAS TRM** (all financial institutions):

| ITSM Practice | MAS TRM Equivalent |
|---|---|
| Change tickets / CAB | §7.2 -- risk assessment, approval, testing, post-implementation review, traceability |
| CMDB | §6.1 -- complete, current IT asset inventory |
| Incident tickets | §11 -- documented response with actions taken and lessons learned |
| Access workflows | §9.1 -- formal request, approval, provisioning, revocation with audit trail |
| Personnel lifecycle | §10.2 -- periodic access review, immediate revocation on role change/departure |

MAS TRM requires initial incident notification within 1 hour --
achievable only with automated ticketing capturing onset/notification/
escalation timestamps. CSA CCCS, Singapore's government cloud
framework, maps to ISO 27001 and FedRAMP with the same evidence
requirements.

**Japan** -- METI Cybersecurity Management Guidelines (Ver 3.0, 2023)
require documented change management, incident tracking, a living
asset inventory, and access lifecycle records. FISC Security
Guidelines (financial institutions) require CAB-equivalent change
review (Ch. 3) and ticketed incident tracking with regulatory reporting
timelines (Ch. 5).

**Australia** -- Essential Eight mitigation strategies with direct
ITSM dependency:

| Essential Eight Strategy | ITSM Dependency |
|---|---|
| Patch applications | Tracked, time-bound remediation tickets with SLA enforcement |
| Restrict administrative privileges | Documented justification/approval via access request tickets |
| Application control | Changes to approved app lists via change tickets |

The ISM (mandatory for government agencies, used by IRAP assessors)
contains 800+ controls across change (ISM-1406, ISM-1219), incident
(ISM-0140, ISM-0576), asset (ISM-1401), and access (ISM-0430, ISM-0441)
that parallel the FedRAMP controls above almost exactly; IRAP requires
documentary evidence, not policy references.

### Commercial Frameworks

**PCI-DSS v4.0** (effective March 2025; assessed by QSAs):

| ITSM Practice | PCI-DSS v4.0 Requirement |
|---|---|
| Change tickets / CAB | Req 6.5 -- documented request, impact analysis, approval, testing, rollback |
| CMDB / Asset inventory | Req 12.5.1 -- documented, current inventory |
| Incident tickets | Req 12.10 -- documented response with roles, timelines, evidence; 12.10.2 annual test |
| Access request workflows | Req 7.2.2/7.2.4 -- documented authorization; access reviewed every 6 months |
| Personnel lifecycle tickets | Req 8.3.4, 8.8 -- terminated-user access managed and documented |
| Document review-due tracking | Req 12.1.2 -- policy reviewed at least annually; review-due date/overdue flag is direct evidence |
| Document acknowledgment | Req 12.6 -- a tracked, per-person acknowledgment record is what a QSA samples |
| Vendor/TPSP register | Req 12.8 -- maintained TPSP list, agreements, annual monitoring; `subprocessor-register.rain` starts the Req 12.8.1 list |
| Encryption key/cert inventory | Req 3.6/3.7 -- documented key lifecycle; `encryption-key-cert-register.rain` covers the inventory half |
| Vulnerability remediation tracking | Req 11.3 -- quarterly scans, tracked remediation; `poam-tracking-fields.rain` adds the risk-rating/deadline metadata |

PCI-DSS v4.0's "customized approach" still requires documented risk
analysis and control-effectiveness evidence -- evidence generation is
non-negotiable either way.

**SOX -- IT General Controls** (all U.S. public companies; ITGCs
tested under PCAOB AS 2201):

| ITGC Domain | ITSM Dependency |
|---|---|
| Change Management | Ticket showing request, approval, testing sign-off, implementation date -- a change without one is an automatic finding |
| Logical Access Controls | Access request tickets, off-boarding records, periodic access review outputs |
| Computer Operations | Incident records with timestamps, owners, resolution notes |
| Program Development | Change/project tickets with approval gates for SDLC changes |

An ITGC material weakness -- e.g. undocumented changes to financial
systems -- can trigger SEC scrutiny, restatement, and personal
liability for the CEO/CFO under Sections 302 and 906.

**ISO/IEC 27001:2022** (certifiable, 3-year cycle with annual
surveillance; recognized in the EU via NIS2, the UK, Canada, Australia,
Japan, Singapore, and more). Annex A control mapping:

| ITSM Practice | ISO 27001:2022 Annex A Control |
|---|---|
| Change tickets / CAB | 8.32 Change Management |
| CMDB | 5.9 Inventory of Information and Other Associated Assets |
| Incident tickets | 5.26 Response to Incidents; 5.27 Learning from Incidents |
| Access workflows | 5.18 Access Rights |
| Personnel lifecycle | 6.5 Responsibilities After Termination |
| Alert-to-ticket automation | 8.16 Monitoring Activities |
| Document review-due tracking | 5.1 Policies for Information Security |
| Document acknowledgment | 6.3 Awareness/Training; 5.10 Acceptable Use |
| Vendor/cloud supplier register | 5.19-5.23 Supplier Relationships (5.23: cloud services) -- `subprocessor-register.rain` / `cloud-environment-register.rain` |
| Encryption key/cert inventory | 8.24 Use of Cryptography -- `encryption-key-cert-register.rain` covers the inventory |
| Configuration management / drift detection | 8.9 -- see [`docs/drift-detection.md`](drift-detection.md) |
| Data classification | 5.12/5.13 -- `data-inventory-register.rain` |
| Vulnerability management | 8.8 -- `poam-tracking-fields.rain` adds remediation-deadline metadata |

ISO 27001 auditors sample changes, incidents, access events, and
off-boarding events, and require the corresponding records -- the same
evidentiary standard as FedRAMP 3PAOs, PCI QSAs, and SOX auditors.

---

### The Universal Principle

Compliance isn't demonstrated by having a policy -- it's demonstrated
by producing evidence the policy was followed, at the moment it needed
to be, for every instance in scope. A policy document describing a
change process isn't evidence a specific change was approved; a ticket
record is. The control identifiers differ -- CM-3, 8.32, Req 6.5,
op.exp.5 -- but the required artifact is the same: a structured,
timestamped, approval-chain-bearing record of what was proposed, who
authorized it, what was done, and when it closed.

---

*Analysis derived from a FedRAMP High authorization package's
implementation statements. Control counts reflect the 409 implemented
controls/enhancements as of the SSP snapshot used for this analysis.
FedRAMP High baseline per FedRAMP Rev 5 / NIST 800-53 Rev 5.*
