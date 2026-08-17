# Controls Requiring IT Service Management Practices

> **FedRAMP High Authorization Package — Reference Analysis**
> This document identifies the controls in a FedRAMP High package where a structured system of record — ticketing, change management workflows, incident records, CMDB, or formal approval processes — is not merely helpful but is the only credible mechanism for satisfying the control requirement. It includes background on FedRAMP, NIST 800-53, and the authorization tiers to establish the compliance context.

---

## Background: NIST 800-53 and Why It Exists

**NIST Special Publication 800-53** (currently Revision 5, published 2020) is the foundational security and privacy controls catalog published by the National Institute of Standards and Technology. It is the technical backbone of U.S. federal information security. The catalog contains **1,189 individual controls and control enhancements** organized into 20 control families (AC, AU, CM, IR, etc.), covering everything from access control and configuration management to supply chain risk and privacy.

800-53 does not prescribe *how* you implement a control — it defines *what* outcome you must achieve and *what evidence* demonstrates you achieved it. That distinction matters: the burden of proof always falls on the system owner to show the control is satisfied in a way an independent assessor can verify. For many controls, especially those requiring authorization, documentation, tracking, and accountability, the only mechanism that generates the required evidence at scale is a system of record with structured workflows.

---

## Background: FedRAMP — What It Is

**FedRAMP (Federal Risk and Authorization Management Program)** is the U.S. government's standardized framework for authorizing cloud services for federal agency use. Established in 2011 and significantly modernized by the **FedRAMP Authorization Act of 2022**, it requires that any cloud product or service used by a federal agency either hold a FedRAMP authorization or be in the process of obtaining one.

FedRAMP takes the NIST 800-53 control catalog and applies it in three scoped tiers based on the **sensitivity of the data being processed or stored**, defined by FIPS 199 impact levels:

| Tier | Impact Level | Required Controls | Typical Use Case |
|---|---|---|---|
| **FedRAMP Low** | Low | ~156 controls | Public-facing, non-sensitive data |
| **FedRAMP Moderate** | Moderate | ~323 controls | Most federal SaaS, CUI, PII |
| **FedRAMP High** | High | ~421 controls | National security, law enforcement, financial, health data |

**The reference package analyzed here is authorized at FedRAMP High**, the most demanding tier. It contains **409 implemented controls and enhancements** across 18 control families, with the additional controls above Moderate primarily focused on stricter access control, more rigorous configuration management, enhanced incident response capabilities, and tighter audit requirements.

---

## FedRAMP's New Authorization Tiers ("Class" Designations)

FedRAMP underwent significant restructuring under the **FedRAMP Authorization Act of 2022** and subsequent OMB policy updates. The program introduced a new tiered designation model sometimes referred to informally by authorization pathway and data sensitivity class:

### FedRAMP Rev 5 Authorization Pathways

| Designation | Description |
|---|---|
| **Agency Authorization** | A single federal agency sponsors and authorizes the CSP. Authorization is granted by that agency's AO (Authorizing Official) and the ATO is reusable by other agencies via the FedRAMP Marketplace. |
| **JAB P-ATO (Program Authorization)** | The Joint Authorization Board — composed of DoD, DHS, and GSA CIOs — reviews and grants a Provisional ATO. This was the highest-prestige path. The JAB was **sunset in 2023** under the new model. |
| **FedRAMP Equivalency** | New pathway (2024+) for DoD-specific cloud services under DoD IL guidance — allows DoD IL2/IL4/IL5/IL6 authorizations to be recognized as FedRAMP-equivalent under certain conditions. |

### Impact-Level Classes (Data Sensitivity Tiers)

The informal "class" terminology maps to FIPS 199 impact levels for confidentiality, integrity, and availability:

| Class | FIPS 199 Level | FedRAMP Tier | Examples |
|---|---|---|---|
| **Class A / Low** | Low | FedRAMP Low | Non-sensitive public data, training content |
| **Class B / Moderate** | Moderate | FedRAMP Moderate | Most agency operational data, CUI, PII |
| **Class C / High** | High | FedRAMP High | Law enforcement, financial systems, health records, national security |
| **Class D / DoD IL4-IL5** | High+ | DoD IL Authorization | Controlled Unclassified Information for DoD; sensitive compartmented operations |
| **Class E / IL6** | Secret | DoD IL6 / Secret Cloud | Classified information at the SECRET level; requires IC-specific cloud infrastructure |

**The reference package operates at FedRAMP High (Class C)**, which means it is authorized to process the most sensitive unclassified federal data — data whose loss, corruption, or unauthorized disclosure could cause severe or catastrophic harm to agency operations, individuals, or national security.

---

## This Package: Control Count Summary

The reference FedRAMP High package contains the following implemented controls by family:

| Family | Name | Controls in Package |
|---|---|---|
| AC | Access Control | 50 |
| AU | Audit and Accountability | 27 |
| CM | Configuration Management | 34 |
| CP | Contingency Planning | 35 |
| IA | Identification and Authentication | 30 |
| IR | Incident Response | 24 |
| SC | System and Communications Protection | 35 |
| SI | System and Information Integrity | 35 |
| SA | System and Services Acquisition | 25 |
| CA | Assessment, Authorization & Monitoring | 16 |
| MA | Maintenance | 12 |
| PE | Physical and Environmental Protection | 25 |
| PS | Personnel Security | 11 |
| RA | Risk Assessment | 13 |
| PL | Planning | 7 |
| AT | Awareness and Training | 6 |
| MP | Media Protection | 10 |
| SR | Supply Chain Risk Management | 14 |
| **Total** | | **409** |

---

## ITSM Coverage Analysis: Where a System of Record Is Required

Of the 409 controls in this package, **33 controls and enhancements** have implementation statements that explicitly require or depend on a structured system of record — a ticketing platform, CMDB, or workflow-driven approval system — to generate the audit evidence the control demands.

### Coverage Numbers

| Metric | Count | % of Package |
|---|---|---|
| Total controls/enhancements in package | 409 | 100% |
| Controls requiring a system of record | **33** | **~8%** |
| Controls where ITSM is the *primary* mechanism | **22** | **~5.4%** |
| Controls where ITSM is a *supporting* mechanism | **11** | **~2.7%** |

> **Why this percentage matters more than it looks:** These 33 controls are not evenly distributed. They are concentrated in the highest-risk, highest-scrutiny control families — Configuration Management, Incident Response, and Access Control — which are the families that receive the most attention from Third-Party Assessment Organizations (3PAOs) during annual assessments. A finding in any of these controls can result in a POA&M (Plan of Action and Milestones), which delays or conditions the Authorization to Operate (ATO). Conversely, demonstrating systematic, tool-enforced compliance through a system of record is the most direct way to achieve "Implemented" status across all 33.

### ITSM Controls by Family

| Family | ITSM Controls | Count | % of That Family |
|---|---|---|---|
| CM — Configuration Management | CM-2, CM-2(2), CM-3, CM-3(1), CM-3(2), CM-8, CM-8(2), CM-9 | 8 | **24%** |
| IR — Incident Response | IR-4, IR-5, IR-5(1), IR-7, IR-7(1) | 5 | **21%** |
| AC — Access Control | AC-2, AC-3, AC-4, AC-6(5), AC-6(7) | 5 | **10%** |
| MA — Maintenance | MA-2, MA-5, MA-5(1) | 3 | **25%** |
| AU — Audit and Accountability | AU-5, AU-5(2), AU-12(3) | 3 | **11%** |
| PS — Personnel Security | PS-4, PS-4(2), PS-5 | 3 | **27%** |
| SI — System and Information Integrity | SI-2, SI-5, SI-6 | 3 | **9%** |
| SA — System and Services Acquisition | SA-10, SA-4(9) | 2 | **8%** |
| SC — System and Communications Protection | SC-7(4) | 1 | **3%** |

The **Maintenance (MA)** and **Personnel Security (PS)** families have the highest proportional dependency on ITSM workflows — over a quarter of each family's controls require structured records. **Configuration Management (CM)** has the highest absolute count, with nearly one in four CM controls requiring a change ticket, CMDB, or approval workflow.

---

## The Controls and Why a System of Record Is the Answer

---

### Change Tickets / Change Advisory Board (CAB / TRB)

These controls demand that nothing changes on the system without a formal, documented, multi-person approval chain — a change ticket is the only practical mechanism that enforces that at scale.

| Control | Title | Why a ticket is required |
|---|---|---|
| **CM-3** | Configuration Change Control | Every change must be proposed, justified, tested, and approved in an auditable record before production. The ticket ties together the requester, approving board, assigned implementer, test evidence, and final disposition in a single traceable record. |
| **CM-3(1)** | Automated Documentation, Notification, and Prohibition of Changes | A workflow-driven change ticket enforces approval gates automatically — it cannot be closed without required sign-offs and generates automatic notifications at each state transition, mechanically enforcing the "prohibition until approval" requirement. |
| **CM-3(2)** | Testing, Validation, and Documentation of Changes | Attaching test results and security impact assessments within the change record creates an auditable package proving the change was not deployed until testing was completed and documented. |
| **CM-2** | Baseline Configuration | Deviations from the approved baseline must be authorized — a change ticket through the approval board creates the formal approval trail proving the baseline was only changed with explicit authorization. |
| **CM-2(2)** | Automation Support for Accuracy and Currency | The CHG record is the audit trail. Every modification is stamped with who requested, who reviewed, who approved, and when implemented — directly supporting accuracy and currency of the recorded baseline. |
| **CM-9** | Configuration Management Plan | Change requests as structured records, combined with a defined inventory of configuration items, operationalize the plan — they demonstrate the process exists and is being followed in practice, not just on paper. |
| **SA-10** | Developer Configuration Management | Developer changes to system components are configuration-controlled. Routing all such changes through a ticketing-based CAB process ensures source code, schemas, and deployment configurations are treated as managed configuration items with full review and audit trail. |
| **SA-4(9)** | Functions, Ports, Protocols, and Services in Use | PPS changes directly affect the attack surface. Requiring TRB approval through a change ticket ensures no new ports or services are opened without security review, and the ticket documents what was approved, why, and by whom. |
| **SC-7(4)** | External Telecommunications Services (Boundary Protection) | Every traffic exception must be CAB-approved before the firewall rule is created. Remediation tickets submitted when unnecessary PPS are found during periodic reviews convert review findings into actual changes rather than just documentation. |
| **AU-12(3)** | Changes by Authorized Individuals | Changes to audit scope are security-sensitive and could be used to suppress visibility into malicious activity. Requiring a TRB-approved change ticket ensures no one can quietly reduce logging without a formal, multi-person review and an auditable record. |
| **SI-2** | Flaw Remediation | Vulnerability scanner findings are converted to time-bound remediation tickets with CAB approval required before production patching, providing a single artifact demonstrating the entire lifecycle from discovery to closure for every flaw. |

---

### CMDB / Configuration Items

These controls require an authoritative inventory of system components — only a configuration management database satisfies the "accurate, current, complete" requirement.

| Control | Title | Why a CMDB is required |
|---|---|---|
| **CM-8** | System Component Inventory | Requires a maintained inventory of all hardware, software, and firmware components throughout the lifecycle. A CMDB is the purpose-built record system for this — it stores component identity, relationships, ownership, and status as the authoritative source of truth auditors expect to see. |
| **CM-8(2)** | Automated Maintenance | Automated discovery feeding directly into a CMDB provides continuous, machine-verified accuracy. Alerts on discrepancies between discovered assets and CMDB records operationalize the "detect unauthorized components" requirement without manual effort. |
| **CM-9** | Configuration Management Plan | Configuration items must be formally defined and placed under management throughout the system development lifecycle. The CMDB is the registry that makes this requirement operational. |

---

### Incident Tickets

These controls require structured tracking of security events from detection through resolution.

| Control | Title | Why a ticket is required |
|---|---|---|
| **IR-4** | Incident Handling | Each phase of incident handling (detection, analysis, containment, eradication, recovery) must be coordinated, timed, and documented. An incident ticket creates the single record tracking all activity from initial detection through closure, capturing timestamps and preserving the chain of custody evidence. |
| **IR-5** | Incident Monitoring | "Track and document" incidents on an ongoing basis is the literal definition of what an incident management ticket provides. Each incident gets a unique record with status, priority, assigned owner, resolution notes, and timestamps. |
| **IR-5(1)** | Automated Tracking, Data Collection, and Analysis | SIEM-to-ticketing integrations that automatically generate an incident record when an alert fires satisfy the "automated tracking" requirement, enabling analysis of trends, SLA compliance, and recurring issues across the incident corpus. |
| **IR-7** | Incident Response Assistance | The NIST control guidance itself names "automated ticketing systems to open and track incident response tickets" as a canonical example of an incident response support resource. |
| **IR-7(1)** | Automation Support for Availability of Information and Support | Automated incident ticket creation from SIEM alerts, with SLA-enforced escalations, ensures incident response support is always available — the ticket triggers the escalation chain automatically so no incident stalls waiting for a human to notice it. |

---

### Access Request Tickets / Approval Workflows

These controls require explicit, documented authorization before any access is provisioned.

| Control | Title | Why a ticket is required |
|---|---|---|
| **AC-2** | Account Management | Every account lifecycle event (create, modify, disable, remove) must have an approval record. A structured access request ticket captures the requester, business justification, approver identity, and date of approval — the auditable record that proves each action was intentional and sanctioned. |
| **AC-3** | Access Enforcement | VPN access and privileged OS accounts require explicit approval from a designated responsible owner before provisioning. The ticket creates the three-party documented chain (requester → approver → implementer) that proves enforcement rather than just policy. |
| **AC-4** | Information Flow Enforcement | Firewall rule changes modify the authorized flow boundary. A change ticket through the approval board ensures every exception is reviewed for security impact before implementation, proving the exception was authorized rather than an undocumented ad-hoc rule. |
| **AC-6(5)** | Privileged Accounts | Every privileged account must be explicitly justified, approved by a designated responsible owner, and provisioned only after that approval — creating a per-account evidence trail that reviewers need to verify least privilege is maintained. |
| **AC-6(7)** | Review of User Privileges | Submitting a remediation ticket to remove unnecessary access converts the finding into a tracked, assignable work item with a due date, ensuring it is actually completed rather than just noted in a review spreadsheet that is never acted upon. |

---

### Maintenance Tickets

These controls require that maintenance events are authorized, escorted, and documented.

| Control | Title | Why a ticket is required |
|---|---|---|
| **MA-2** | Controlled Maintenance | A maintenance ticket captures what work was done, by whom, deadlines, and approval — distinguishing "controlled maintenance" from unplanned, undocumented work on production systems and satisfying the formal scheduling, approval, and documentation requirements. |
| **MA-5** | Maintenance Personnel | When a vendor or external technician is engaged, a ticket documents who was given access, who escorted them, what work they performed, and when access was terminated — the personnel accountability record proving escort and oversight requirements were met. |
| **MA-5(1)** | Individuals Without Appropriate Access | The access and repair ticket is reviewed at closure to confirm all required actions (escort assigned, equipment sanitized, access revoked) were completed before the ticket was resolved — converting the procedural requirement into a verifiable checklist. |

---

### Audit and Accountability Tickets

These controls require that audit failures generate tracked, actionable work items rather than just alerts.

| Control | Title | Why a ticket is required |
|---|---|---|
| **AU-5** | Response to Audit Logging Process Failures | Automatically generating a ticket when an audit failure alert fires creates an assignable, SLA-bound work item that forces a response. The ticket provides evidence that required personnel were notified and corrective action was taken. |
| **AU-5(2)** | Real-time Alerts | Real-time alert routing into automated ticket creation satisfies both immediacy (real-time) and accountability (someone must acknowledge and resolve) simultaneously. The ticket requires a human to close it, proving the alert was received and acted upon. |
| **AU-12(3)** | Changes by Authorized Individuals | *(See Change Tickets section above — also applies here as an audit control.)* |

---

### Personnel Workflow Tickets

These controls require checklisted, multi-team workflows that cannot be reliably executed without a structured work item.

| Control | Title | Why a ticket is required |
|---|---|---|
| **PS-4** | Personnel Termination | Off-boarding spans multiple teams and systems. A parent off-boarding record with child tasks assigned to each responsible team creates a checklist-driven workflow where every access point is verifiably revoked and evidence is attached. |
| **PS-4(2)** | Automated Actions | An automated off-boarding ticket generated upon termination triggers the notification email to all operational and security distribution lists automatically, creating the task record with a deadline — removing the human-dependency lag that is the most common failure mode in access termination. |
| **PS-5** | Personnel Transfer | A structured transfer ticket with a checklist of access items to revoke and new items to provision ensures role changes are treated with the same rigor as new hires or terminations, preventing accumulation of stale entitlements. |

---

### System Integrity Tickets

These controls require that security findings, advisories, and verification failures generate tracked corrective action.

| Control | Title | Why a ticket is required |
|---|---|---|
| **SI-2** | Flaw Remediation | *(See Change Tickets section above — also applies here as an integrity control.)* |
| **SI-5** | Security Alerts, Advisories, and Directives | An automatic ticket generated per government security advisory ensures every directive is formally assigned for review and the outcome is recorded. Without a tracked work item, there is no way to demonstrate each advisory received attention rather than being silently ignored. |
| **SI-6** | Security Function Verification | When a security function verification failure is detected (e.g., an AV coverage gap), the ticket formally assigns corrective work to the responsible team with a deadline — converting the SOC observation into an obligation with a traceable resolution. |

---

## Summary: Why a System of Record Is Not Optional

Across 33 controls in this FedRAMP High package, the compliance requirement cannot be satisfied by policy documents, spreadsheets, or informal processes alone. The table below summarizes the ITSM capability required and the compliance outcome it enables:

| ITSM Capability | Controls Dependent | What Happens Without It |
|---|---|---|
| **Change tickets with CAB/TRB approval** | 11 controls | Changes made without documented approval → findings on CM-3, SI-2, AC-4, SA-10 |
| **CMDB / Configuration item registry** | 3 controls | No authoritative asset inventory → findings on CM-8, CM-9 |
| **Incident tickets with lifecycle tracking** | 5 controls | No proof incidents were handled, tracked, or resolved → findings on IR-4, IR-5, IR-7 |
| **Access request tickets with approval chain** | 5 controls | No evidence access was explicitly authorized → findings on AC-2, AC-3, AC-6 |
| **Maintenance records with escort/work detail** | 3 controls | No proof maintenance was controlled or personnel were vetted → findings on MA-2, MA-5 |
| **Alert-to-ticket automation** | 2 controls | Alerts acknowledged but not actioned → findings on AU-5 |
| **Personnel workflow tickets (on/off-boarding)** | 3 controls | Access not verifiably revoked → findings on PS-4, PS-5 |

FedRAMP High assessors (3PAOs) do not accept verbal attestation or policy references as evidence for these controls. They require artifacts: ticket numbers, timestamps, approval records, closure notes, and trend data. A structured IT service management platform is the mechanism that generates those artifacts continuously and at scale, making the difference between a clean annual assessment and a POA&M backlog that conditions the ATO.

---

*Analysis derived from a FedRAMP High authorization package implementation statements. Control counts reflect the 409 implemented controls/enhancements in the reference package as of the SSP snapshot used for this analysis. FedRAMP High baseline per FedRAMP Rev 5 / NIST 800-53 Rev 5.*
