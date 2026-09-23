"""TEST-ONLY providers. The running application never uses canned responses (SRS 1.8.12).

ScriptedProvider builds its answer from the prompt it receives (it reads the [R-...] markers and the
document / section headers), so the whole pipeline can be tested without calling Gemini.
"""
import json
import re

from genai_pipeline.providers import ProviderError, ProviderResponse

HEADER = re.compile(r"^=== (\S+) v\S+ ·", re.M)
SECTION = re.compile(r"^\[§([^\]]+)\]", re.M)
MARKER = re.compile(r"\[(R-[A-Z0-9-]+)\]\s*([^\[\n]*)")
REQ_LINE = re.compile(r"^- (R-[A-Z0-9-]+) \(mandatory: (yes|no), due: (\w+)\)", re.M)


def _clauses(sources):
    """{req_id: (doc_id, section_id, clause text)} from a prompt's source block."""
    found, doc, section = {}, None, None
    for line in sources.splitlines():
        h, s = HEADER.match(line), SECTION.match(line)
        if h:
            doc = h.group(1)
        if s:
            section = s.group(1)
        for m in MARKER.finditer(line):
            found[m.group(1)] = (doc, section, m.group(2).strip())
    return found


class ScriptedProvider:
    def __init__(self, drop_first_mandatory=False, invent_fact=False, spread_categories=False):
        self.drop_first_mandatory, self.invent_fact = drop_first_mandatory, invent_fact
        self.spread_categories = spread_categories      # one knowledge area per document -> several modules
        self.calls = 0

    def _category(self, doc):
        if not self.spread_categories or not doc:
            return "Company Orientation"
        from config.loader import load_config
        areas = list(load_config("extraction")["competencies"])
        return areas[sum(map(ord, doc)) % len(areas)]

    def generate(self, model, system, user, schema):
        self.calls += 1
        sources = user.split("<source_documents>")[-1]
        clauses = _clauses(sources)
        if schema.__name__ == "PlanOutline":
            reqs = []
            for rid, (doc, section, text) in clauses.items():
                mandatory = bool(re.search(r"\b(must|shall|required|prohibited|may only)\b", text, re.I))
                reqs.append({"requirement_id": rid, "mandatory": mandatory, "priority": "Medium", "due_stage": "W1",
                             "category": self._category(doc), "source_document_id": doc, "source_section_id": section})
            if self.drop_first_mandatory:
                first = next(r for r in reqs if r["mandatory"])
                reqs.remove(first)
                self.dropped = first["requirement_id"]
            body = {"requirements": reqs, "excluded": [], "insufficient_information": []}
        else:
            wanted = REQ_LINE.findall(user)
            ids = [rid for rid, _, _ in wanted]
            objective = "Explain the rules in this module."
            if self.invent_fact:
                objective = "Keep hot food at 63 °C before service."
            checklist, quiz = [], []
            for rid, mandatory, stage in wanted:
                doc, section, text = clauses.get(rid, ("?", "?", ""))
                checklist.append({"activity": f"Confirm you understand {rid}", "required": mandatory == "yes",
                                  "due_stage": stage, "responsible": "Line manager", "requirement_id": rid,
                                  "source_document_id": doc, "source_section_id": section})
                quiz.append({"type": "multiple_choice", "question": f"What does {rid} require?",
                             "options": [text, "Nothing at all"], "correct_options": [0], "explanation": text,
                             "difficulty": "Beginner", "requirement_id": rid, "source_document_id": doc,
                             "source_section_id": section})
            body = {"module_key": "M01", "title": "Scripted module", "purpose": "Test content.",
                    "learning_objectives": [{"text": objective, "requirement_ids": ids}], "key_concepts": [],
                    "required_sources": [], "estimated_duration_minutes": 30, "activities": [],
                    "checklist": checklist, "tasks": [], "scenarios": [], "quiz": quiz,
                    "assessment": {"type": "knowledge", "topic": "Module rules",
                                   "rubric": [{"criterion": "Accuracy", "weight": 60, "expected_performance": "Correct",
                                               "pass_condition": "80%"},
                                              {"criterion": "Completeness", "weight": 40, "expected_performance": "All",
                                               "pass_condition": "80%"}]},
                    "completion_criteria": "Pass the quiz."}
        return ProviderResponse(text=json.dumps(body), model=model, latency_ms=5, tokens_in=100, tokens_out=100)


class SequenceProvider:
    """Replays a list of outcomes: an exception instance to raise, or a text to return."""

    def __init__(self, outcomes):
        self.outcomes, self.models = list(outcomes), []

    def generate(self, model, system, user, schema):
        self.models.append(model)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return ProviderResponse(text=outcome, model=model, latency_ms=1)


def unavailable():
    return ProviderError("unavailable", "503 high demand", 503)


def rate_limited():
    return ProviderError("rate_limit", "429 quota", 429)


def unauthorised():
    return ProviderError("auth", "401 invalid key", 401)
