# Controls Requiring IT Service Management Practices

> This document maps compliance controls -- across FedRAMP/NIST 800-53 and a dozen other major frameworks worldwide -- to the specific ITSM capability that satisfies them: a change ticket, an incident record, a CMDB entry, an access-approval workflow. The headline finding: in a real FedRAMP High authorization package, close to **one in ten implemented controls** requires a structured system of record as the *only* credible way to produce evidence an assessor accepts. Run RAIN as your ticketing/asset/document system of record and you're generating that evidence just by using it day to day -- not as a separate compliance exercise bolted on afterward.

---

## Why a System of Record, Not a Policy Document

NIST SP 800-53 (Rev 5) -- the security/privacy controls catalog behind FedRAMP and most other U.S. federal frameworks -- defines *what* outcome a control requires, not *how* to implement it. The burden of proof falls on the system owner to produce evidence an independent assessor accepts. For a large slice of controls -- authorization, tracking, accountability -- the only mechanism that generates that evidence at scale is a system of record with structured workflows: a ticket, a CMDB entry, an approval chain.

FedRAMP is the reference dataset used throughout this document because it's a rigorously assessed framework with public, itemized control language -- not because the finding is FedRAMP-specific. See "Cross-Framework Applicability" below: the same dependency, worded differently, shows up in German BSI, French ANSSI, ISO 27001, PCI-DSS, SOX, and half a dozen other frameworks. The reference package analyzed here is a real FedRAMP High authorization: 409 implemented controls and enhancements across 18 control families.

---

## ITSM Coverage Analysis: Where a System of Record Is Required

Of the 409 controls in this reference implementation, 33 controls and enhancements have implementation statements that explicitly require or depend on a structured system of record -- a ticketing platform, CMDB, or workflow-driven approval system -- to generate the audit evidence the control demands. That's close to one in ten controls in the package satisfied, as a byproduct, by nothing more than running that system of record as your day-to-day tool -- not a compliance program layered on top of it.

### Coverage Numbers

| Metric | Count | % of Package |
|---|---|---|
| Total controls/enhancements in package | 409 | 100% |
| Controls requiring a system of record | 33 | ~8% |
| Controls where ITSM is the *primary* mechanism | 22 | ~5.4% |
| Controls where ITSM is a *supporting* mechanism | 11 | ~2.7% |

> Why this percentage matters more than it looks: These 33 controls are not evenly distributed. They are concentrated in the highest-risk, highest-scrutiny control families -- Configuration Management, Incident Response, and Access Control -- which are the families that receive the most attention from Third-Party Assessment Organizations (3PAOs) during annual assessments. A finding in any of these controls can result in a POA&M (Plan of Action and Milestones), which delays or conditions the Authorization to Operate (ATO). Conversely, demonstrating systematic, tool-enforced compliance through a system of record is the most direct way to achieve "Implemented" status across all 33.

### ITSM Controls by Family

| Family | ITSM Controls | Count | % of That Family |
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

The Maintenance (MA) and Personnel Security (PS) families have the highest proportional dependency on ITSM workflows -- over a quarter of each family's controls require structured records. Configuration Management (CM) has the highest absolute count, with nearly one in four CM controls requiring a change ticket, CMDB, or approval workflow.

---

## The Controls and Why a System of Record Is the Answer

---

### Change Tickets / Change Advisory Board (CAB / TRB)

These controls demand that nothing changes on the system without a formal, documented, multi-person approval chain -- a change ticket is the only practical mechanism that enforces that at scale.

| Control | Title | Why a ticket is required |
|---|---|---|
| CM-3 | Configuration Change Control | Every change must be proposed, justified, tested, and approved in an auditable record before production. The ticket ties together the requester, approving board, assigned implementer, test evidence, and final disposition in a single traceable record. |
| CM-3(1) | Automated Documentation, Notification, and Prohibition of Changes | A workflow-driven change ticket enforces approval gates automatically -- it cannot be closed without required sign-offs and generates automatic notifications at each state transition, mechanically enforcing the "prohibition until approval" requirement. |
| CM-3(2) | Testing, Validation, and Documentation of Changes | Attaching test results and security impact assessments within the change record creates an auditable package proving the change was not deployed until testing was completed and documented. |
| CM-2 | Baseline Configuration | Deviations from the approved baseline must be authorized -- a change ticket through the approval board creates the formal approval trail proving the baseline was only changed with explicit authorization. |
| CM-2(2) | Automation Support for Accuracy and Currency | The CHG record is the audit trail. Every modification is stamped with who requested, who reviewed, who approved, and when implemented -- directly supporting accuracy and currency of the recorded baseline. |
| CM-9 | Configuration Management Plan | Change requests as structured records, combined with a defined inventory of configuration items, operationalize the plan -- they demonstrate the process exists and is being followed in practice, not just on paper. |
| SA-10 | Developer Configuration Management | Developer changes to system components are configuration-controlled. Routing all such changes through a ticketing-based CAB process ensures source code, schemas, and deployment configurations are treated as managed configuration items with full review and audit trail. |
| SA-4(9) | Functions, Ports, Protocols, and Services in Use | PPS changes directly affect the attack surface. Requiring TRB approval through a change ticket ensures no new ports or services are opened without security review, and the ticket documents what was approved, why, and by whom. |
| SC-7(4) | External Telecommunications Services (Boundary Protection) | Every traffic exception must be CAB-approved before the firewall rule is created. Remediation tickets submitted when unnecessary PPS are found during periodic reviews convert review findings into actual changes rather than just documentation. |
| AU-12(3) | Changes by Authorized Individuals | Changes to audit scope are security-sensitive and could be used to suppress visibility into malicious activity. Requiring a TRB-approved change ticket ensures no one can quietly reduce logging without a formal, multi-person review and an auditable record. |
| SI-2 | Flaw Remediation | Vulnerability scanner findings are converted to time-bound remediation tickets with CAB approval required before production patching, providing a single artifact demonstrating the entire lifecycle from discovery to closure for every flaw. |

---

### CMDB / Configuration Items

These controls require an authoritative inventory of system components -- only a configuration management database satisfies the "accurate, current, complete" requirement.

| Control | Title | Why a CMDB is required |
|---|---|---|
| CM-8 | System Component Inventory | Requires a maintained inventory of all hardware, software, and firmware components throughout the lifecycle. A CMDB is the purpose-built record system for this -- it stores component identity, relationships, ownership, and status as the authoritative source of truth auditors expect to see. |
| CM-8(2) | Automated Maintenance | Automated discovery feeding directly into a CMDB provides continuous, machine-verified accuracy. Alerts on discrepancies between discovered assets and CMDB records operationalize the "detect unauthorized components" requirement without manual effort. |
| CM-9 | Configuration Management Plan | Configuration items must be formally defined and placed under management throughout the system development lifecycle. The CMDB is the registry that makes this requirement operational. |

---

### Incident Tickets

These controls require structured tracking of security events from detection through resolution.

| Control | Title | Why a ticket is required |
|---|---|---|
| IR-4 | Incident Handling | Each phase of incident handling (detection, analysis, containment, eradication, recovery) must be coordinated, timed, and documented. An incident ticket creates the single record tracking all activity from initial detection through closure, capturing timestamps and preserving the chain of custody evidence. |
| IR-5 | Incident Monitoring | "Track and document" incidents on an ongoing basis is the literal definition of what an incident management ticket provides. Each incident gets a unique record with status, priority, assigned owner, resolution notes, and timestamps. |
| IR-5(1) | Automated Tracking, Data Collection, and Analysis | SIEM-to-ticketing integrations that automatically generate an incident record when an alert fires satisfy the "automated tracking" requirement, enabling analysis of trends, SLA compliance, and recurring issues across the incident corpus. |
| IR-7 | Incident Response Assistance | The NIST control guidance itself names "automated ticketing systems to open and track incident response tickets" as a canonical example of an incident response support resource. |
| IR-7(1) | Automation Support for Availability of Information and Support | Automated incident ticket creation from SIEM alerts, with SLA-enforced escalations, ensures incident response support is always available -- the ticket triggers the escalation chain automatically so no incident stalls waiting for a human to notice it. |

---

### Access Request Tickets / Approval Workflows

These controls require explicit, documented authorization before any access is provisioned.

| Control | Title | Why a ticket is required |
|---|---|---|
| AC-2 | Account Management | Every account lifecycle event (create, modify, disable, remove) must have an approval record. A structured access request ticket captures the requester, business justification, approver identity, and date of approval -- the auditable record that proves each action was intentional and sanctioned. |
| AC-3 | Access Enforcement | VPN access and privileged OS accounts require explicit approval from a designated responsible owner before provisioning. The ticket creates the three-party documented chain (requester → approver → implementer) that proves enforcement rather than just policy. |
| AC-4 | Information Flow Enforcement | Firewall rule changes modify the authorized flow boundary. A change ticket through the approval board ensures every exception is reviewed for security impact before implementation, proving the exception was authorized rather than an undocumented ad-hoc rule. |
| AC-6(5) | Privileged Accounts | Every privileged account must be explicitly justified, approved by a designated responsible owner, and provisioned only after that approval -- creating a per-account evidence trail that reviewers need to verify least privilege is maintained. |
| AC-6(7) | Review of User Privileges | Submitting a remediation ticket to remove unnecessary access converts the finding into a tracked, assignable work item with a due date, ensuring it is actually completed rather than just noted in a review spreadsheet that is never acted upon. |

---

### Maintenance Tickets

These controls require that maintenance events are authorized, escorted, and documented.

| Control | Title | Why a ticket is required |
|---|---|---|
| MA-2 | Controlled Maintenance | A maintenance ticket captures what work was done, by whom, deadlines, and approval -- distinguishing "controlled maintenance" from unplanned, undocumented work on production systems and satisfying the formal scheduling, approval, and documentation requirements. |
| MA-5 | Maintenance Personnel | When a vendor or external technician is engaged, a ticket documents who was given access, who escorted them, what work they performed, and when access was terminated -- the personnel accountability record proving escort and oversight requirements were met. |
| MA-5(1) | Individuals Without Appropriate Access | The access and repair ticket is reviewed at closure to confirm all required actions (escort assigned, equipment sanitized, access revoked) were completed before the ticket was resolved -- converting the procedural requirement into a verifiable checklist. |

---

### Audit and Accountability Tickets

These controls require that audit failures generate tracked, actionable work items rather than just alerts.

| Control | Title | Why a ticket is required |
|---|---|---|
| AU-5 | Response to Audit Logging Process Failures | Automatically generating a ticket when an audit failure alert fires creates an assignable, SLA-bound work item that forces a response. The ticket provides evidence that required personnel were notified and corrective action was taken. |
| AU-5(2) | Real-time Alerts | Real-time alert routing into automated ticket creation satisfies both immediacy (real-time) and accountability (someone must acknowledge and resolve) simultaneously. The ticket requires a human to close it, proving the alert was received and acted upon. |
| AU-12(3) | Changes by Authorized Individuals | *(See Change Tickets section above -- also applies here as an audit control.)* |

---

### Personnel Workflow Tickets

These controls require checklisted, multi-team workflows that cannot be reliably executed without a structured work item.

| Control | Title | Why a ticket is required |
|---|---|---|
| PS-4 | Personnel Termination | Off-boarding spans multiple teams and systems. A parent off-boarding record with child tasks assigned to each responsible team creates a checklist-driven workflow where every access point is verifiably revoked and evidence is attached. |
| PS-4(2) | Automated Actions | An automated off-boarding ticket generated upon termination triggers the notification email to all operational and security distribution lists automatically, creating the task record with a deadline -- removing the human-dependency lag that is the most common failure mode in access termination. |
| PS-5 | Personnel Transfer | A structured transfer ticket with a checklist of access items to revoke and new items to provision ensures role changes are treated with the same rigor as new hires or terminations, preventing accumulation of stale entitlements. |

---

### System Integrity Tickets

These controls require that security findings, advisories, and verification failures generate tracked corrective action.

| Control | Title | Why a ticket is required |
|---|---|---|
| SI-2 | Flaw Remediation | *(See Change Tickets section above -- also applies here as an integrity control.)* |
| SI-5 | Security Alerts, Advisories, and Directives | An automatic ticket generated per government security advisory ensures every directive is formally assigned for review and the outcome is recorded. Without a tracked work item, there is no way to demonstrate each advisory received attention rather than being silently ignored. |
| SI-6 | Security Function Verification | When a security function verification failure is detected (e.g., an AV coverage gap), the ticket formally assigns corrective work to the responsible team with a deadline -- converting the SOC observation into an obligation with a traceable resolution. |

---

## Summary: Why a System of Record Is Not Optional

Across 33 controls in this FedRAMP High package, the compliance requirement cannot be satisfied by policy documents, spreadsheets, or informal processes alone. The table below summarizes the ITSM capability required and the compliance outcome it enables:

| ITSM Capability | Controls Dependent | What Happens Without It |
|---|---|---|
| Change tickets with CAB/TRB approval | 11 controls | Changes made without documented approval → findings on CM-3, SI-2, AC-4, SA-10 |
| CMDB / Configuration item registry | 3 controls | No authoritative asset inventory → findings on CM-8, CM-9 |
| Incident tickets with lifecycle tracking | 5 controls | No proof incidents were handled, tracked, or resolved → findings on IR-4, IR-5, IR-7 |
| Access request tickets with approval chain | 5 controls | No evidence access was explicitly authorized → findings on AC-2, AC-3, AC-6 |
| Maintenance records with escort/work detail | 3 controls | No proof maintenance was controlled or personnel were vetted → findings on MA-2, MA-5 |
| Alert-to-ticket automation | 2 controls | Alerts acknowledged but not actioned → findings on AU-5 |
| Personnel workflow tickets (on/off-boarding) | 3 controls | Access not verifiably revoked → findings on PS-4, PS-5 |

FedRAMP High assessors (3PAOs) do not accept verbal attestation or policy references as evidence for these controls. They require artifacts: ticket numbers, timestamps, approval records, closure notes, and trend data. A structured IT service management platform is the mechanism that generates those artifacts continuously and at scale, making the difference between a clean annual assessment and a POA&M backlog that conditions the ATO.

---

## Moderate and Low Baselines

The 33-control figure above is specific to this High package, but it isn't a High-specific *dependency*: most of these (19 of 33) are base controls, not enhancements, and base controls survive down into the smaller baselines even as enhancements drop away. Directionally, the same roughly-one-in-ten proportion holds at Moderate and Low too -- Low if anything comes out slightly ahead, since the technical/cryptographic controls that dilute the percentage at higher tiers aren't in its baseline to begin with. The takeaway isn't tied to which FedRAMP tier you target.

## Native Mechanisms Added Since This Analysis

The 33-control count reflects a single SSP-snapshot analysis (see the methodology note at the end of this document) and hasn't been re-run since. Three controls that used to sit in Indirect Coverage below -- "can use RAIN's primitives with some implementation judgment" -- have since gained a dedicated, purpose-built mechanism instead:

- AC-2(3) (Disable Accounts) -- `last_login_at` is a dedicated column, stamped on every sign-in and exported straight to CSV from Admin > Users, not a report someone has to think to go build.
- PL-4 (Rules of Behavior) / PS-6 (Access Agreements) -- a document's "Requires acknowledgment from" is a dedicated feature (a group-or-user requirement, a tracked-pending state surfaced in the client portal, an automatic email, a Platform Response Rule trigger), not a voluntary click an admin hopes people use.
- PL-2 (System Security Plan), supporting tier -- a document's review-due date is a dedicated field with an overdue flag and filter, not a note in a spreadsheet about when the SSP was last opened.

That's a real promotion out of "requires judgment" into the same category the 33 already uses. What it isn't is a re-stated 37/409 headline: the 33 was counted control-by-control against one specific reference package's actual implementation-statement language, family by family (see the "% of That Family" column above), and a defensible new total needs that same source material and methodology, not just a plausible-sounding new number. Left open rather than guessed at.

## Indirect Coverage

A second set of controls, outside the 33, aren't ticket-shaped by nature but can use RAIN's ticket/document/calendar primitives as their evidence mechanism with some implementation judgment. Several are also shipped as ready-to-import starter bundles under [`docs/compliance-templates/`](compliance-templates/) (asset types plus fields, or -- for CA-5 below -- ticket fields), cited inline where one exists -- a template lowers the cost of setting one of these up, it doesn't change a control's classification here, so importing one doesn't move anything out of this list and into the 33:

- CA-5 (POA&M) -- a POA&M item is structurally a ticket (finding, owner, due date, closure), open to whichever ticket type the underlying finding actually is (usually vulnerability); the strongest indirect fit here. A starter POA&M tracking-fields bundle template (`docs/compliance-templates/poam-tracking-fields.json`) adds the FedRAMP-specific metadata -- POA&M ID, finding source, CVE/finding ID, original risk rating, scheduled completion date, point of contact, deviation type and justification -- as ticket custom fields rather than asset fields, since a POA&M item's lifecycle (opened, tracked, closed or risk-accepted) is a ticket's lifecycle, not a persistent asset's; it's the one starter template scoped to tickets instead of assets. One real gap: FedRAMP's own POA&M template expects discrete, individually-dated milestones per item, and RAIN has no first-class milestone list -- a ticket's timestamped comment thread and status history is the practical substitute, not a literal replacement.
- RA-5 / RA-7 (Vulnerability Scanning / Risk Response) -- RAIN is the remediation-tracking half, not the scanner. A starter Nessus finding-fields bundle template (`docs/compliance-templates/nessus-finding-fields.json`) adds the scanner-native metadata (plugin ID, CVSS score, port/protocol, the scanner's own risk factor) as ticket custom fields, close enough to Tenable's own CSV export column names that a scan's findings map onto them through the existing CSV ticket importer today. The importer's own opt-in "Dedup key" mapping (`Ticket.external_finding_key`, migration 0050) makes a recurring monthly re-scan of the same environment safe to just re-import instead of a one-time-only bulk load: a still-open match is left alone (custom fields still refresh), a closed match is reopened and flagged recurring (`is_problematic`) rather than duplicated.
- RA-3 (Risk Assessment) -- a starter Risk Register bundle template (`docs/compliance-templates/risk-register.json`) turns this from a from-scratch custom-asset-type build into a five-minute import.
- CP-4 (Contingency Plan Testing), PE-3 / PE-6 (Physical/Visitor Access), SR-2 / SR-6 (Supply Chain Reviews), MP-6 (Media Sanitization) -- each loggable as a ticket or recurring calendar entry, same pattern as MA-5(1)'s escort/sanitization tracking in the direct 33; SR-2/SR-6 specifically now also has a starter Subprocessor Register bundle template (`docs/compliance-templates/subprocessor-register.json`).
- IA-2 / PE-2 (Identification and Authentication / Physical Access Authorizations), with a PS-3 (Personnel Screening) assist -- a starter PIV/CAC Card issuance bundle template (`docs/compliance-templates/piv-cac-card-issuance.json`) tracks the credential itself (serial/FASC-N, card type, issuing agency, issue/expiration dates, status) alongside the sponsoring official and background investigation tier behind it, as a custom asset type rather than a spreadsheet kept outside the system of record.
- CM-10 (Software Usage Restrictions) -- a starter Software License bundle template (`docs/compliance-templates/software-license-register.json`) tracks vendor, license type, seat count, renewal date, and status per license, complementing CM-8's own component inventory (in the direct 33) with the licensing/entitlement half CM-8 doesn't cover.
- CM-8(3) (Automated Unauthorized Component Detection) / SI-7 (Software, Firmware, and Information Integrity) -- a document populated from a scheduled infrastructure-discovery run (Terraform + a discovery tool against the live account) alerts the moment two consecutive snapshots differ, the same diff-on-refresh mechanism every webhook-populated document already has (see "Infrastructure drift detection" in `docs/user-guide.md`). This is detection of the *undocumented* change -- the verification half CM-2's own baseline (already in the direct 33) needs and CM-3's own approval trail (also in the direct 33) doesn't provide by itself -- the three together are what "every change was both approved and is the only thing that happened" actually takes. A starter Cloud Environment bundle template (`docs/compliance-templates/cloud-environment-register.json`) tracks the account/environment this applies to.
- SC-12 / SC-13 (Cryptographic Key Establishment and Management / Cryptographic Protection) -- a starter Encryption Key/Certificate bundle template (`docs/compliance-templates/encryption-key-cert-register.json`) tracks the lifecycle (issued/expiration dates, algorithm, issuer, rotation owner, status) of every managed key and certificate; it holds no key material, just the inventory a rotation/expiry review needs.
- CA-3 (System Interconnections) -- a starter System Interconnection bundle template (`docs/compliance-templates/system-interconnection-register.json`) tracks each system-to-system connection, its authorization and review dates, and status; the actual Interconnection Security Agreement links in as a Document the same way any other reference document does.
- PS-7 (Third-Party Personnel Security) -- a starter Contractor Access bundle template (`docs/compliance-templates/contractor-access-register.json`) tracks the individual, not the company (the Subprocessor Register's own level): sponsor, access level, background-check status, and engagement dates per contractor.
- RA-2 (Security Categorization) -- a starter Data Inventory bundle template (`docs/compliance-templates/data-inventory-register.json`) tracks data category, classification level, owner, and retention period per identified data holding, a basic data inventory rather than the full data-flow mapping RA-2 ultimately asks for.

---

## Cross-Framework Applicability: These Requirements Are Not Unique to FedRAMP

The ITSM practices described in this document -- change tickets, incident records, CMDB, access request workflows, and personnel lifecycle tracking -- are not artifacts of U.S. federal policy. They are the universal operational evidence layer demanded by virtually every major information security and compliance framework worldwide. The requirement for a system of record is a global constant. What varies is the name of the framework and the specific control identifier, not the underlying obligation.

The sections below map the ITSM categories in this document to their equivalents across major commercial and international regulatory frameworks.

---

### European Union

#### Germany -- BSI IT-Grundschutz (Federal Office for Information Security)

Germany's BSI IT-Grundschutz (IT Baseline Protection) is one of the most rigorous national frameworks in Europe, published and maintained by the Bundesamt für Sicherheit in der Informationstechnik (BSI). It is mandatory for German federal agencies and widely adopted by German critical infrastructure operators and financial institutions.

| ITSM Practice | IT-Grundschutz Equivalent |
|---|---|
| Change tickets / CAB approval | OPS.1.1.3 (Patch and Change Management) -- requires documented change requests, impact assessment, and approval before implementation |
| CMDB / Asset inventory | ORP.4 (Identity and Permission Management) + SYS family modules -- require maintained inventories of all systems and components |
| Incident tickets | DER.2.1 (Incident Management) -- requires systematic detection, reporting, and tracking of security incidents through a defined process |
| Access request workflows | ORP.4 -- requires formal provisioning and revocation processes with documented authorization |
| Personnel lifecycle tickets | ORP.2 (Personnel) -- requires documented procedures for onboarding, transfer, and offboarding with tracked access revocation |

IT-Grundschutz takes a "building block" approach where each module maps directly to a process area. The change management, incident management, and identity management building blocks all explicitly require that evidence of the process be generated and retained -- the same evidentiary requirement driving ITSM use in FedRAMP.

---

#### France -- ANSSI SecNumCloud and RGS

France's national cybersecurity agency, ANSSI (Agence nationale de la sécurité des systèmes d'information), publishes two primary frameworks:

- SecNumCloud -- the qualification standard for cloud service providers handling sensitive government data, roughly analogous to FedRAMP High
- RGS (Référentiel Général de Sécurité) -- the baseline security framework for French public administration

| ITSM Practice | ANSSI Framework Equivalent |
|---|---|
| Change tickets / CAB | SecNumCloud §10 (Change Management) -- requires a formal change management process with traceability from request to closure |
| Incident tickets | SecNumCloud §13 (Incident Management) -- requires a ticketed, tracked incident lifecycle with defined escalation paths and reporting timelines |
| CMDB | SecNumCloud §8 (Asset Management) -- requires a continuously maintained inventory of all assets in scope |
| Access workflows | SecNumCloud §9 (Access Control) -- requires documented provisioning and revocation with approval records |

SecNumCloud qualification requires third-party audit of these processes. Assessors specifically look for evidence of tooling -- a process described in a policy document without an operational system of record generating artifacts will not pass qualification.

---

#### Netherlands -- BIO (Baseline Informatiebeveiliging Overheid)

The BIO is the Dutch government's unified information security baseline, mandatory across all layers of Dutch public administration (central government, municipalities, provinces, and water boards). It is based directly on ISO/IEC 27001/27002 and maps its controls to that standard.

| ITSM Practice | BIO / ISO 27002:2022 Equivalent |
|---|---|
| Change tickets / CAB | ISO 27002 §8.32 (Change Management) -- requires formal change request, risk assessment, approval, and post-implementation review |
| CMDB | ISO 27002 §5.9 (Inventory of Information and Other Associated Assets) -- requires maintained, accurate asset inventory |
| Incident tickets | ISO 27002 §5.26 (Response to Information Security Incidents) -- requires documented incident response with evidence of containment, eradication, and recovery |
| Access workflows | ISO 27002 §5.18 (Access Rights) -- requires formal provisioning, review, and revocation processes with documented authorization |
| Personnel lifecycle | ISO 27002 §6.5 (Responsibilities After Termination or Change of Employment) -- requires timely, documented revocation of access on departure or role change |

Because BIO maps directly to ISO 27001, any organization certified to ISO 27001 is simultaneously satisfying the Dutch BIO requirements -- and ISO 27001 certification auditors will specifically sample change records, incident tickets, and access provisioning evidence during Stage 2 audits.

---

#### Spain -- ENS (Esquema Nacional de Seguridad)

Spain's ENS (National Security Framework), governed by Royal Decree 311/2022, is mandatory for all Spanish public administration bodies and cloud service providers that process public administration data. It defines three security levels (Basic, Medium, High) roughly analogous to FedRAMP's Low/Moderate/High tiers.

| ITSM Practice | ENS Equivalent |
|---|---|
| Change tickets / CAB | op.exp.5 (Change Management) -- requires formal documentation, approval, and traceability for all changes to production systems |
| Incident tickets | op.exp.7 (Incident Management) -- requires systematic recording, classification, and tracking of security incidents |
| CMDB | op.inv.1 (Asset Inventory) -- requires a current, accurate inventory of all assets within the security boundary |
| Access workflows | op.acc.4 (Access Rights Management) -- requires documented access provisioning and revocation with an audit trail |
| Personnel lifecycle | mp.per.3 (Personnel Departure) -- requires revocation of credentials and access upon departure with documented evidence |

At ENS High level -- the tier applicable to systems processing sensitive government data -- assessors require evidence artifacts, not just policy declarations. The framework explicitly states that "procedures must be capable of being verified."

---

#### Poland -- KSC (Ustawa o Krajowym Systemie Cyberbezpieczeństwa)

Poland's KSC Act (Act on the National Cybersecurity System, 2018), implementing the EU NIS Directive, establishes security requirements for operators of essential services and digital service providers. It references both ISO/IEC 27001 and NIST CSF as acceptable implementation frameworks.

| ITSM Practice | KSC / NIS2 Equivalent |
|---|---|
| Incident tickets | KSC Art. 8 -- requires systematic incident detection, handling, and reporting; incidents must be recorded and reported to the national CSIRT within defined timeframes |
| Change tickets | ISO 27001 Annex A 8.32 (as referenced by KSC) -- formal change management with documented approval |
| CMDB | KSC Art. 8(1)(b) -- requires identification and management of all systems and assets within the security scope |
| Access workflows | KSC Art. 8(1)(d) -- requires access control with documented authorization and revocation |

Notably, the EU NIS2 Directive (2022/2555), which supersedes NIS and which all EU member states -- including Germany, France, the Netherlands, Spain, and Poland -- must implement, explicitly requires in Article 21 that covered entities employ "incident handling," "business continuity," "supply chain security," and "access control" measures with evidence of implementation. NIS2 applies to a significantly broader set of organizations than NIS1 and carries administrative fines of up to €10 million or 2% of global turnover for non-compliance.

---

### Canada

#### Government of Canada -- ITSG-33 / GC PBMM

The Treasury Board of Canada Secretariat (TBS) publishes ITSG-33 (IT Security Risk Management: A Lifecycle Approach) as the foundational security control framework for Canadian federal departments. The control catalog is derived directly from NIST 800-53, making the mapping between frameworks nearly one-to-one.

For cloud services, the Government of Canada uses the Protected B, Medium Integrity, Medium Availability (PBMM) profile as the baseline for most departmental cloud workloads -- roughly equivalent to FedRAMP Moderate -- and a Protected B High profile for sensitive workloads.

| ITSM Practice | ITSG-33 / GC Equivalent |
|---|---|
| Change tickets / CAB | CM-3 (directly inherited from NIST 800-53) -- identical requirement for formal change control with documented approval |
| CMDB | CM-8 (directly inherited) -- identical system component inventory requirement |
| Incident tickets | IR-4, IR-5 (directly inherited) -- identical incident handling and monitoring requirements |
| Access workflows | AC-2, AC-3 (directly inherited) -- identical account management and access enforcement requirements |
| Personnel lifecycle | PS-4, PS-5 (directly inherited) -- identical personnel termination and transfer requirements |

Because ITSG-33 mirrors NIST 800-53, any organization that has implemented ITSM-backed compliance for FedRAMP has effectively satisfied the corresponding Canadian federal requirements with the same tooling and the same artifacts. The Canadian Centre for Cyber Security (CCCS) cloud assessment process specifically requests evidence of automated change management and incident tracking as part of cloud service provider assessments.

Additionally, the Office of the Superintendent of Financial Institutions (OSFI) Guideline B-13 (Technology and Cyber Risk Management, effective 2023) requires federally regulated financial institutions -- banks, insurers, pension funds -- to maintain formal change management processes, incident management with defined response timelines, and asset inventories. OSFI B-13 assessments require artifact evidence, not narrative descriptions.

---

### Asia-Pacific

#### Singapore -- MAS TRM Guidelines and CSA CCCS

Singapore operates two major frameworks relevant to ITSM-backed compliance:

MAS TRM (Monetary Authority of Singapore -- Technology Risk Management Guidelines) applies to all financial institutions in Singapore and is one of the most prescriptive financial sector frameworks in Asia.

| ITSM Practice | MAS TRM Equivalent |
|---|---|
| Change tickets / CAB | MAS TRM §7.2 (Change Management) -- requires a formal change management process with risk assessment, approval, testing, and post-implementation review; changes must be traceable |
| CMDB | MAS TRM §6.1 (IT Asset Management) -- requires a complete, current inventory of all IT assets |
| Incident tickets | MAS TRM §11 (Cyber Incident Response and Management) -- requires a documented incident response process with records of each incident, actions taken, and lessons learned |
| Access workflows | MAS TRM §9.1 (Access Control) -- requires formal access request, approval, provisioning, and revocation with an audit trail |
| Personnel lifecycle | MAS TRM §10.2 (User Access Review) -- requires periodic access reviews and immediate revocation upon role change or departure |

MAS TRM requires financial institutions to submit incident reports for significant technology incidents within defined timeframes (1 hour for initial notification), which is only operationally achievable with automated incident ticketing that captures onset time, notification time, and escalation records.

CSA CCCS (Cyber Security Agency -- Cloud Computing Security Framework) is Singapore's government cloud security framework, used for assessing cloud service providers for government use. It maps to ISO 27001 and FedRAMP, with explicit requirements for change management records, incident logs, and access provisioning evidence.

---

#### Japan -- METI Cybersecurity Management Guidelines and FISC

Japan's primary ITSM-relevant frameworks:

METI Cybersecurity Management Guidelines (経済産業省 サイバーセキュリティ経営ガイドライン, Ver 3.0, 2023) -- published by the Ministry of Economy, Trade and Industry, applies to corporations with significant IT dependencies. It requires senior management accountability for cybersecurity and explicitly calls for:

- Documented change management processes with approval records
- Incident management with detection-to-resolution tracking
- Asset inventory maintained as a living document
- Access lifecycle management with records

FISC Security Guidelines (Center for Financial Industry Information Systems) -- mandatory guidance for Japanese financial institutions. FISC Chapter 3 (Operations Management) requires formal change management with CAB-equivalent review, and Chapter 5 (Incident Management) requires ticketed incident tracking with defined escalation paths and regulatory reporting timelines.

---

#### Australia -- Essential Eight and IRAP / ISM

Australia's Australian Cyber Security Centre (ACSC) publishes two frameworks:

The Essential Eight is a prioritized set of eight mitigation strategies. While relatively concise, several directly require ITSM capabilities:

| Essential Eight Strategy | ITSM Dependency |
|---|---|
| Patch applications (ML1-ML3) | Requires tracked, time-bound patch remediation -- operationalized through change/remediation tickets with SLA enforcement |
| Restrict administrative privileges (ML1-ML3) | Requires documented justification and approval for privileged accounts -- operationalized through access request tickets |
| Application control | Changes to approved application lists must be formally managed -- operationalized through change tickets |

ISM (Information Security Manual) -- the full Australian government security framework, mandatory for government agencies and used by the IRAP (Infosec Registered Assessors Program) assessment process. The ISM contains over 800 controls across change management (ISM-1406, ISM-1219), incident management (ISM-0140, ISM-0576), asset management (ISM-1401), and access control (ISM-0430, ISM-0441) that parallel the FedRAMP controls in this document almost exactly. IRAP assessors require documentary evidence of each control, not policy references.

---

### Commercial Frameworks

#### PCI-DSS v4.0 (Payment Card Industry Data Security Standard)

PCI-DSS applies to any organization that stores, processes, or transmits payment card data. Version 4.0 (effective March 2025) significantly strengthened evidence requirements across change management and access control. It is assessed by Qualified Security Assessors (QSAs) who require artifact evidence.

| ITSM Practice | PCI-DSS v4.0 Requirement |
|---|---|
| Change tickets / CAB | Req 6.5 (Changes to all system components are managed securely) -- requires a formal change management process including documented change requests, security impact analysis, approval by authorized parties, testing, and rollback procedures. Each change must have a documented record. |
| CMDB / Asset inventory | Req 12.5.1 -- requires a documented inventory of all system components in scope, kept current. |
| Incident tickets | Req 12.10 (Implement an incident response plan) -- requires documented incident response with defined roles, timelines, and evidence of response actions taken. Req 12.10.2 requires the plan be reviewed and tested at least annually, with evidence. |
| Access request workflows | Req 7.2.2 -- requires formal user access request and approval processes, with access provisioned only after documented authorization. Req 7.2.4 requires all user accounts and access privileges to be reviewed at least once every 6 months. |
| Personnel lifecycle tickets | Req 8.3.4 -- invalid authentication attempts must be locked; Req 8.8 -- requires all access policies for terminated users to be managed and documented. |
| Document review-due tracking | Req 12.1.2 -- the security policy must be reviewed and, if needed, updated at least once every 12 months. A document's own review-due date and overdue flag are direct evidence of that cadence, not a note in a spreadsheet. |
| Document acknowledgment | Req 12.6 (Security awareness program) -- personnel must receive security awareness education and, in practice, formally acknowledge the security policy; a tracked, followed-up, per-person acknowledgment record (see "Requires acknowledgment from" on a document) is exactly the evidence a QSA samples, not an open-ended "training happened." |
| Vendor/TPSP register | Req 12.8 (Manage information security with service providers) -- requires a maintained list of third-party service providers, written agreements, and monitoring of each TPSP's own PCI-DSS compliance status at least annually. A starter Subprocessor Register bundle template (`docs/compliance-templates/subprocessor-register.json`) is a five-minute start on the Req 12.8.1 list itself. |
| Encryption key/cert inventory | Req 3.6 / 3.7 (Cryptographic key management) -- keys used to protect stored account data need documented generation, distribution, storage, rotation, and retirement procedures. A starter Encryption Key/Certificate bundle template (`docs/compliance-templates/encryption-key-cert-register.json`) tracks the inventory half of that -- not the key management procedure itself. |
| Vulnerability remediation tracking | Req 11.3 (Internal and external vulnerability scans) -- requires quarterly scans with tracked remediation and re-scanning until high-risk vulnerabilities are resolved. A starter POA&M tracking-fields bundle template (`docs/compliance-templates/poam-tracking-fields.json`) adds the risk-rating/remediation-deadline metadata onto the vulnerability ticket that already tracks this. |

PCI-DSS v4.0 introduced the concept of a "customized approach" -- organizations can implement alternative controls, but must provide documented evidence of risk analysis and compensating control effectiveness to their QSA. In all cases, evidence generation is non-negotiable. A QSA will request change records, access provisioning tickets, and incident logs as primary evidence during a Report on Compliance (RoC) assessment.

---

#### SOX -- Sarbanes-Oxley Act (IT General Controls)

SOX applies to all publicly traded companies in the United States (and foreign private issuers listed on U.S. exchanges). While SOX is a financial reporting law, its IT General Controls (ITGCs) -- assessed under frameworks like COBIT and tested by external auditors under PCAOB AS 2201 -- overlap significantly with the ITSM requirements in this document.

The four ITGC domains most relevant to ITSM are:

| ITGC Domain | ITSM Dependency |
|---|---|
| Change Management | External auditors test that all changes to financial systems went through a formal, documented approval process. Evidence required: change tickets showing request, approval, testing sign-off, and implementation date. A change implemented without a ticket is an automatic finding. |
| Logical Access Controls | Auditors test that user access is provisioned based on formal requests with documented approval, that access is removed promptly upon termination, and that privileged access is reviewed periodically. Evidence required: access request tickets, off-boarding records, and user access review outputs. |
| Computer Operations | Auditors test that production incidents affecting financial reporting systems are detected, tracked, and resolved in a documented manner. Evidence required: incident records with timestamps, assigned owners, and resolution notes. |
| Program Development | Auditors test that new systems or significant changes went through a documented SDLC with security review and approval. Evidence required: change/project tickets with approval gates. |

SOX ITGC findings (deficiencies) must be disclosed in the company's annual report. A material weakness in ITGCs -- such as changes to financial systems made without documented approval -- can trigger SEC scrutiny, require restatement of financials, and result in personal liability for the CEO and CFO who certify the controls under Sections 302 and 906. This makes SOX ITGC compliance one of the highest-stakes drivers of enterprise change management and access control tooling adoption.

---

#### ISO/IEC 27001:2022 -- International Standard for Information Security Management Systems

ISO 27001 is the globally recognized certification standard for information security management. It is certifiable, meaning organizations undergo third-party audit by an accredited certification body and receive a formal certificate valid for three years with annual surveillance audits. It is recognized or mandated in the EU (via NIS2 as an accepted compliance path), the UK, Canada, Australia, Japan, Singapore, and dozens of other jurisdictions.

Annex A of ISO 27001:2022 contains 93 controls organized into four themes. The following map directly to the ITSM practices in this document:

| ITSM Practice | ISO 27001:2022 Annex A Control |
|---|---|
| Change tickets / CAB | 8.32 Change Management -- formal change management process with documented requests, risk assessment, approval, and review |
| CMDB | 5.9 Inventory of Information and Other Associated Assets -- maintained, accurate, current asset inventory |
| Incident tickets | 5.26 Response to Information Security Incidents -- documented incident response with evidence of actions taken; 5.27 Learning from Incidents -- requires incident records to enable trend analysis |
| Access workflows | 5.18 Access Rights -- formal provisioning, modification, and revocation of access rights with documented authorization |
| Personnel lifecycle | 6.5 Responsibilities After Termination -- access revocation upon departure or role change with documented evidence |
| Alert-to-ticket automation | 8.16 Monitoring Activities -- anomalies must be evaluated and responded to; response must be documented |
| Document review-due tracking | 5.1 Policies for Information Security -- policies must be reviewed at planned intervals. |
| Document acknowledgment | 6.3 Information Security Awareness, Education and Training, and 5.10 Acceptable Use of Information and Other Associated Assets -- both expect a documented, per-person acknowledgment trail, not an open-ended "training happened." |
| Vendor/cloud supplier register | 5.19-5.23 (Supplier Relationships) -- information security in supplier relationships, supplier agreements, the ICT supply chain, monitoring/review of supplier services, and (5.23, added in the 2022 revision) use of cloud services specifically. Starter Subprocessor Register and Cloud Environment bundle templates (`docs/compliance-templates/subprocessor-register.json`, `docs/compliance-templates/cloud-environment-register.json`) cover the vendor and cloud-account halves respectively. |
| Encryption key/cert inventory | 8.24 Use of Cryptography -- a policy on cryptographic controls, including key management. A starter Encryption Key/Certificate bundle template (`docs/compliance-templates/encryption-key-cert-register.json`) tracks the inventory, not the key management procedure itself. |
| Configuration management / drift detection | 8.9 Configuration Management -- establish, document, and monitor configuration baselines. The infrastructure-drift-detection pattern (see "Infrastructure drift detection" in `docs/user-guide.md`) is direct evidence of the monitoring half. |
| Data classification | 5.12 Classification of Information / 5.13 Labelling of Information -- a starter Data Inventory bundle template (`docs/compliance-templates/data-inventory-register.json`) tracks classification level per identified data asset. |
| Vulnerability management | 8.8 Management of Technical Vulnerabilities -- identify, evaluate, and treat technical vulnerabilities in a timely manner. A starter POA&M tracking-fields bundle template (`docs/compliance-templates/poam-tracking-fields.json`) adds the remediation-deadline metadata onto the vulnerability ticket that already tracks this. |

ISO 27001 certification auditors conduct evidence sampling: they will select a random sample of changes, incidents, access provisioning events, and off-boarding events and ask to see the corresponding records. An organization that says "we have a change management process" but cannot produce change records for sampled events will receive a nonconformity. This is the same evidentiary standard applied by FedRAMP 3PAOs, PCI QSAs, and SOX auditors -- and it is why a system of record is not optional under any of these frameworks.

---

### The Universal Principle

Across all of the frameworks above -- U.S. federal, European, Canadian, Asia-Pacific, and commercial -- the same underlying principle applies: compliance is not demonstrated by having a policy; it is demonstrated by producing evidence that the policy was followed, at the moment it needed to be followed, for every instance in scope. A policy document that describes a change management process is not evidence that a specific change was approved. A ticket record is. An incident response plan is not evidence that a specific incident was handled correctly. An incident record with timestamps, assigned owners, and resolution notes is.

This is why a system of record is the convergence point for compliance across frameworks. The specific control identifiers differ -- CM-3 in NIST, 8.32 in ISO 27001, Req 6.5 in PCI-DSS, op.exp.5 in ENS -- but the evidence artifact they all require is the same: a structured, timestamped, approval-chain-bearing record of what was proposed, who authorized it, what was done, and when it was closed.

---

*Analysis derived from a FedRAMP High authorization package implementation statements. Control counts reflect the 409 implemented controls/enhancements in the reference package as of the SSP snapshot used for this analysis. FedRAMP High baseline per FedRAMP Rev 5 / NIST 800-53 Rev 5.*
