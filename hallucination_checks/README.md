# hallucination_checks

Deterministic checks that stop the application from teaching things the approved documents do not say
(SRS Steps 31-32 and the hallucination challenge in §1.8).

| Layer | Where | What it does |
|---|---|---|
| Topic support | `topic_support.py`, page **Knowledge > Topic check** | Before anything is written, decides whether the approved passages cover a requested topic: *supported*, *review* (a person decides) or *unsupported* (refused). Thresholds in `config/hallucination.yaml`. |
| Item support | `python_validation/rules.py` (V-HALLUCINATION, V-SOURCE, V-REQ-ID, V-QUIZ-SOURCE) | After generation, flags each item whose cited source does not back it. Results appear on the plan page and in the *Hallucination flags* report. |
| Model's own gaps | plan page, *What the sources do not cover* | Topics the model itself reported as not covered by the sources (`insufficient_information` in the outline JSON). |

None of these call a GenAI API: the model writes, Python decides.
