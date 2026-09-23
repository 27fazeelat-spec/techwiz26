# Requirement extraction accuracy

Measured against the gold register in `documentation/dataset/03_Requirements_Register.csv` (external and 'Not Applicable' items excluded).

| Measure | Result |
|---|---|
| Gold requirements | 184 |
| Extracted (register versions) | 183 |
| Matched | 183 |
| **Recall** | **99.5%** |
| **Precision** | **100.0%** |
| Mandatory / optional correct | 100.0% |
| Requirement type correct | 88.5% |
| Section ID correct | 100.0% |
| Due stage correct | 50.8% |
| Priority correct | 67.2% |
| Competency correct | 88.5% |
| Roles exactly right | 70.5% |
| Roles overlap (mean Jaccard) | 82.5% |
| Conditions detected (of gold conditional) | 64.7% |
| Conditions wrongly added | 0 |

## Missed (1)

- `R-RD3-005` ROL-03 §3.3: HR Executives are the first point of contact for employee relations queries at property level.

## Extracted but not in the register (0)

