# Aurelle Hotels & Residences: Company Profile

## 1. Organisation

**Aurelle Hospitality Group** operates *Aurelle Hotels & Residences*, a mid-size upscale hotel and serviced-apartment brand founded in 2009.

| | |
|---|---|
| Headquarters | Corporate Office, Dubai, UAE |
| Employees | ~2,400 across 12 properties and the corporate office |
| Countries | United Arab Emirates, Oman, Malaysia |
| Loyalty programme | Aurelle Circle |
| Reporting currency in policies | USD, or local-currency equivalent |
| Core systems | Property Management System (PMS), Sales & Catering system, ERP (finance), HR portal, maintenance system, incident system |

All organisations, people, properties and policies are fictional. Policies state *company* rules only. They never cite or paraphrase real national laws, so the GenAI model cannot "helpfully" fill in real regulations. That leakage becomes a detectable hallucination.

### Properties (12)

| Code | Property | Country | Type | Notes used by the dataset |
|---|---|---|---|---|
| DXB-HBR | Aurelle Harbourside Dubai | UAE | Hotel | Flagship; 24-hour in-room dining |
| DXB-DTN | Aurelle Downtown Dubai | UAE | Hotel | Events-heavy |
| DXB-MRN | Aurelle Residences Marina | UAE | Residences | Long-stay rules apply |
| AUH-CRN | Aurelle Corniche Abu Dhabi | UAE | Hotel | |
| MCT-BAY | Aurelle Muscat Bay | Oman | Hotel | Main restaurant *Al Bahr*; **no in-room dining service** |
| MCT-QRM | Aurelle Residences Qurum | Oman | Residences | |
| SLL-GDN | Aurelle Salalah Gardens | Oman | Hotel | Outdoor pool complex |
| KUL-BBT | Aurelle Bukit Bintang | Malaysia | Hotel | Malaysia consent rule |
| KUL-MKR | Aurelle Residences Mont Kiara | Malaysia | Residences | |
| PEN-HTG | Aurelle Penang Heritage | Malaysia | Hotel | In-room dining; **missing from IRD-01 Annex A** (case M03) |
| LGK-SHR | Aurelle Langkawi Shores | Malaysia | Hotel | |
| PEN-GTN | Aurelle Residences Georgetown | Malaysia | Residences | |

### Departments

Front Office · Guest Relations · Housekeeping · Food & Beverage · Engineering & Maintenance · Sales & Events · Revenue Management · Finance · Human Resources · IT · Security & Safety · Hotel Management (Duty Managers)

## 2. Job roles (10)

| Code | Role | Department | Reports to | What makes this role's plan distinct |
|---|---|---|---|---|
| FOA | Front Office Associate | Front Office | Front Office Manager | Guest ID and passport handling, payments, check-in/out, key control, night audit when on nights |
| GRE | Guest Relations Executive | Guest Relations | Guest Relations Manager | Complaints and service recovery limits, VIP handling, data privacy in conversation |
| HKS | Housekeeping Supervisor | Housekeeping | Executive Housekeeper | Room inspection, DND and welfare checks, chemicals, lost & found |
| FBA | F&B Associate | Food & Beverage | Outlet Manager | Food safety temperatures, allergens, in-room dining (conditional on assignment) |
| MTT | Maintenance Technician | Engineering | Chief Engineer | Permit to work, lockout/tagout, hot work (conditional), pool duty (conditional), PPE exception to uniform |
| SEE | Sales & Events Executive | Sales & Events | Director of Sales | Contracts, group deposits, BEOs, displacement analysis |
| RVA | Revenue Analyst | Revenue Management | Director of Revenue | Rate integrity, overrides, pick-up and forecast reporting |
| FNA | Finance Associate | Finance | Finance Manager | Three-way match, card settlement, city ledger credit, night audit review |
| HRE | HR Executive | Human Resources | HR Manager | Right-to-work checks, personnel files, employee data confidentiality |
| DMG | Duty Manager | Hotel Management | Hotel Manager | Escalation authority, evacuation lead, fee waivers, service recovery up to USD 300 |

**Hidden-role rehearsal:** *Night Auditor (NAU)*. This role is deliberately **not** in the base role list. Its role description is in the hidden-test pack (H03). The existing SOP-FO-02 and PCH-01 already contain its requirements, so the app should map it without code changes.

**Experience levels:** Beginner (0–1 yr hospitality), Intermediate (2–5 yrs), Advanced (5+ yrs). Levels drive difficulty (SRS Step 25) and one experience-conditional rule (R-FO1-008).

## 3. Demo employee profiles

Input data, created through the UI or a seed script. No sensitive personal data (SRS Step 9). Each profile is chosen to trigger a specific rule.

| ID | Name | Role | Level | Previous experience | Property | Joining | Reporting manager | Triggers |
|---|---|---|---|---|---|---|---|---|
| E001 | Leila Haddad | FOA | Beginner | 1 yr retail customer service | DXB-HBR | 2026-10-05 | Omar Siddiqui | Baseline FOA plan |
| E002 | Arjun Menon | FOA | Intermediate | 3 yrs city-hotel front desk | DXB-MRN | 2026-10-12 | Rania Aziz | R-FO1-008 (skip classroom), R-FO1-009 (Residences) |
| E003 | Nurul Aina Rahman | GRE | Intermediate | 2 yrs airline customer care | KUL-BBT | 2026-10-05 | Daniel Lim | R-GDP-007 (Malaysia consent) |
| E004 | Mateus Oliveira | HKS | Advanced | 7 yrs resort housekeeping | MCT-BAY | 2026-09-28 | Aisha Al-Harthy | Advanced difficulty |
| E005 | Grace Tan | FBA | Beginner | None | PEN-HTG | 2026-10-19 | Marcus Yeo | Assigned to in-room dining; IRD-01 applies, but Annex A has no hours for PEN-HTG → manual review (M03) |
| E006 | Yusuf Al-Balushi | MTT | Intermediate | 4 yrs building maintenance; hot-work certified; pool duty | SLL-GDN | 2026-10-05 | Tariq Al-Said | R-EN1-005, R-HSP-006 conditions true |
| E007 | Sofia Petrova | SEE | Intermediate | 3 yrs MICE sales | DXB-DTN | 2026-10-12 | Laura Bennett | Deposit conflict C09 |
| E008 | Daniel Okafor | RVA | Advanced | 6 yrs revenue management | Corporate | 2026-10-05 | Meera Pillai | Corporate-only plan |
| E009 | Hana Kobayashi | FNA | Beginner | Accounting graduate | AUH-CRN | 2026-11-02 | Khalid Hassan | Finance plan |
| E010 | Priya Raman | HRE | Intermediate | 3 yrs HR generalist | LGK-SHR | 2026-10-19 | Siti Hamzah | Employee-data rules; injected HR paragraph A06 |
| E011 | Karim Mansour | DMG | Advanced | 8 yrs hotel operations | DXB-HBR | 2026-09-28 | Hotel Manager | Widest plan; authority limits |
| E012 | Farah Qureshi | FBA | Intermediate | 2 yrs café service | MCT-BAY | 2026-10-12 | Salim Al-Rawahi | Same role as E005, but **no** in-room dining modules (property has no IRD service): role-relevance within one role |

## 4. Policy precedence hierarchy

Stored in `config/precedence.yaml` in the app. This table is the documented hierarchy the SRS requires (Step 34).

| Tier | Source type | Examples |
|---|---|---|
| 1 | Compliance instructions and company policies (latest approved version) | CMP-01, ISP-01, GDP-01, PCH-01, FLS-01, HSP-01, HRP-01, LVP-01, COC-01, REV-01 |
| 2 | Department SOPs and procedures | SOP-FO-01/02, SOP-HK-01/02, SOP-EN-01, SOP-GR-01, FSA-01, IRD-01, ESC-01, SAL-01, FIN-01, HRS-01, ITA-01 |
| 3 | Role descriptions | ROL-01, ROL-02, ROL-03 |
| 4 | Employee handbook | HBK-01 |
| 5 | FAQs | FAQ-01 |
| 6 | Informal guidance | MEM-01 |
| — | **Never authoritative:** external/partner documents, drafts, expired documents, documents not yet effective | PTR-01, ISP-01 v3 DRAFT, SOP-HK-02 (expired), HSP-01 v2 (until 2026-11-01), NEWS-01 |

**Resolution rules**, applied in order:

1. **Same document lineage:** the latest approved, currently effective version wins. Older versions become *superseded*.
2. **Different tiers:** the higher tier wins.
3. **Life-safety override:** if a lower-tier document is *stricter* on injury, fire, medical or evacuation matters, the stricter rule applies. The item is marked *Verified with Warning* and the document owner is notified. (Case C11)
4. **Same tier, different documents:** no automatic winner. The item gets *Manual Review Required*. (Case C09)
5. Every resolution records which rule decided it, so the UI can explain the outcome.

## 5. Onboarding stages

Configurable in `config/stages.yaml`: **Day 1 · Week 1 · Week 2 · First 30 Days · First 60 Days · First 90 Days** (codes `D1, W1, W2, D30, D60, D90`).

Business rule (SRS Step 13): Day 1 carries at most the requirements tagged `D1` in the matrix, plus acknowledgements. The planner must not pull later requirements forward to Day 1.

## 6. Document-writing conventions (for the team writing the documents)

**Structure of a standard document:**
1. **Metadata header block:** Document ID, Title, Version, Status, Effective Date, Review/Expiry Date, Owner Department, Category, Applies To, Supersedes.
2. Purpose, Scope, Definitions.
3. Numbered body sections (`2.1`, `2.2` …). Each requirement sits in the section given in the register.
4. Revision history table (versioned documents only). The app must detect changes by diffing, **never** by trusting this table.

**Deliberately non-standard documents,** so ingestion doesn't depend on our own format:
- MEM-01: no metadata header, no section numbers (a plain memo)
- PTR-01: no header, "Clause 7"-style numbering, external letterhead
- FAQ-01: `Q1`, `Q2` … numbering instead of sections
- NEWS-01: newsletter layout, no requirements at all

**Requirement wording:**

| Meaning | Wording to use | Extracted as |
|---|---|---|
| Mandatory | must, must not, shall, is required to, is prohibited, may only, will not be approved | Must Know / Complete / Demonstrate / Acknowledge |
| Recommended | should, is encouraged to, is recommended | Recommended |
| Permission | may, can | Optional |
| Information | descriptive text with no obligation | *Not a requirement* |

- About **20% of mandatory clauses use alternate phrasing** ("is required to", "are responsible for", "is prohibited"), so the extractor cannot succeed by matching "must" alone.
- About **40% of each document is informational text** (purpose, background, examples) that must **not** be extracted. This tests SRS Step 11: "distinguish mandatory requirements from informational content".
- **Similar terminology, used on purpose:** "Duty Manager" / "Manager on Duty (MOD)" (ESC-01), "guest folio" / "guest bill" (SOP-FO-01), "room attendant" / "housekeeper". The app keeps a synonym list in `config/glossary.yaml`.
- Paste each `clause_text` from the register verbatim. Wording around it is free.
- Length: 2–5 pages per document; the handbook 8–10.
- **Formats:** roughly half PDF and half DOCX, as listed in the register. Both mandatory formats get parsing, page (PDF) and paragraph (DOCX) references.
