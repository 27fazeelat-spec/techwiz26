"""Hallucination checks (SRS Steps 31-32, §1.8 challenge 8).

Two layers, both deterministic Python:

* Per generated item: python_validation.rules flags content whose cited source does not support it
  (V-HALLUCINATION, V-SOURCE, V-REQ-ID, V-QUIZ-SOURCE); those findings feed the "Hallucination flags" report.
* Per topic, before anything is generated: topic_support.assess() decides whether the approved documents
  cover a requested topic at all. If they do not, the application refuses instead of inventing company rules.
"""
from hallucination_checks.topic_support import TopicResult, assess

__all__ = ["TopicResult", "assess"]
