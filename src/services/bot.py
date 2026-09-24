"""Ask the bot: an employee's question answered only from approved passages, then checked by Python.

    1. The question is scanned for prompt injection. An attack is refused before anything else happens.
    2. Python finds the passages (the Topic check's word matching) among active, non-quarantined source passages
       that apply to the employee's role. Passages whose rule lost a conflict are left out.
    3. Nothing relevant: the bot says the documents do not cover it and Gemini is not asked.
    4. Otherwise Gemini answers from those passages only, as JSON with the passage labels it used.
    5. Python checks the answer: every citation must be one of the passages given, and every number, time and
       amount in the answer must appear in the cited passages. A failed check hides the answer; the employee
       sees the passages themselves.
    6. The employee can send any question to their line manager, who replies in SkillSprint.
Every call is logged as a GenerationRun (phase "ask"). Demo visitors' questions are answered but never stored.
"""
import re
from collections import defaultdict
from datetime import datetime, time as dtime

from sqlalchemy import func, select

from config.loader import load_config
from database import audit, db, utcnow
from database.models import BotQuestion, Chunk, Conflict, Document, GenerationRun, Organization, Requirement
from genai_pipeline import prompts
from genai_pipeline.client import call_structured
from genai_pipeline.providers import ProviderError, build_provider, model_names
from hallucination_checks import assess
from python_validation.facts import unsupported
from schemas.bot import BotAnswer
from security import scan_document

OPEN_CONFLICT = ("manual_review", "auto_resolved_warning")


def cfg():
    return load_config("bot")


def asked_today(employee, day):
    start = datetime.combine(day, dtime.min)
    return db.session.scalar(select(func.count()).select_from(BotQuestion)
                             .where(BotQuestion.employee_id == employee.id, BotQuestion.created_at >= start)) or 0


def passages_for(employee, module_key=None, plan=None):
    """Approved passages this employee may be answered from: [{ref, doc_id, section_id, text, requirements}]."""
    from src.services.conflicts import losing_requirement_ids
    role = employee.job_role.code
    losers = losing_requirement_ids()
    rows = db.session.execute(select(Chunk.id, Chunk.doc_id, Chunk.section_id, Chunk.heading, Chunk.text, Chunk.hidden_text)
                              .join(Document, Chunk.document_id == Document.id)
                              .where(Chunk.doc_status == "active", Chunk.quarantined.is_(False), Document.tier > 0)).all()
    reqs = defaultdict(list)
    for chunk_pk, req_pk, req_id, roles in db.session.execute(
            select(Requirement.chunk_id, Requirement.id, Requirement.req_id, Requirement.roles)
            .join(Document, Requirement.document_id == Document.id)
            .where(Document.status == "active", Requirement.review_status != "rejected")):
        reqs[chunk_pk].append((req_pk, req_id, roles or []))
    only = None
    if module_key and plan is not None:
        module = next((m for m in plan.modules if m.module_key == module_key), None)
        only = {i.source_doc_id for i in (module.items if module else []) if i.source_doc_id} or None
    out = []
    for pk, doc_id, section, heading, text, hidden in rows:
        mine = reqs.get(pk, [])
        if any(r[0] in losers for r in mine):
            continue                                                  # the other document's rule applies
        if mine and not any("ALL" in r[2] or role in r[2] for r in mine):
            continue                                                  # rules for other roles only
        if only is not None and doc_id not in only:
            continue
        if hidden:
            text = " ".join(" ".join(text.split()).replace(" ".join(hidden.replace("​", "").split()), " ").split())
        out.append({"ref": pk, "doc_id": doc_id, "section_id": section, "text": f"{heading} {text}".strip(),
                    "requirements": [r[1] for r in mine], "requirement_pks": [r[0] for r in mine]})
    return out


def _expand(question, synonyms):
    """The question plus the policy words for its everyday words (config/bot.yaml), for finding passages only."""
    words = re.findall(r"[a-z]+", question.lower())
    extra = [synonyms[w] for w in words if w in synonyms]
    return " ".join([question] + extra)


def _injection(question):
    result = scan_document([{"chunk_id": "question", "text": question}])
    return next((f for f in result.findings), None)


def _open_conflicts(requirement_pks):
    if not requirement_pks:
        return []
    rows = db.session.scalars(select(Conflict).where(Conflict.status.in_(OPEN_CONFLICT), Conflict.kind == "cross_document",
                                                     (Conflict.left_requirement_id.in_(requirement_pks)) |
                                                     (Conflict.right_requirement_id.in_(requirement_pks)))).all()
    return [c.conflict_code for c in rows]


def check_answer(parsed, given):
    """Python's decision on Gemini's answer. given: {label: passage}. Returns (ok, check dict)."""
    labels = list(dict.fromkeys(parsed.citations))
    unknown = [l for l in labels if l not in given]
    cited = [given[l] for l in labels if l in given]
    check = {"citations": labels, "unknown_citations": unknown}
    if not parsed.answerable:
        return False, {**check, "reason": "The model said the passages do not answer the question."}
    if unknown or not cited:
        return False, {**check, "reason": "The answer cited a passage it was not given, or cited nothing."}
    missing = unsupported(parsed.answer, "\n".join(p["text"] for p in cited))
    if missing:
        return False, {**check, "missing_facts": sorted(missing),
                       "reason": f"The answer states {', '.join(sorted(missing))}, which the cited passages do not."}
    return True, {**check, "reason": "Every citation was given and every number in the answer is in the cited passages."}


def ask(question, employee, actor, app_config, module_key=None, plan=None, provider=None, save=True):
    """Answer a question. Returns a BotQuestion (added to the session only when save is True)."""
    c = cfg()
    question = " ".join((question or "").split())[: c["max_question_chars"]]
    row = BotQuestion(employee_id=employee.id, module_key=module_key, question=question, status="no_source", score=0.0,
                      check={}, sources=[], created_at=utcnow())
    attack = _injection(question)
    if attack:
        row.status = "blocked"
        row.check = {"reason": "The question reads like an instruction to the AI, so it was not sent to the model.",
                     "technique": attack.technique}
        return _finish(row, actor, save)

    search = _expand(question, c.get("synonyms") or {})
    passages = passages_for(employee, module_key, plan)
    result = assess(search, passages, supported_at=1.01, review_at=c["answer_from"], max_matches=c["passages"],
                    extra_stopwords=c.get("extra_stopwords", []))
    if module_key and not result.matches:                             # nothing in the module's sources: try them all
        passages = passages_for(employee)
        result = assess(search, passages, supported_at=1.01, review_at=c["answer_from"], max_matches=c["passages"],
                        extra_stopwords=c.get("extra_stopwords", []))
    row.score = result.score
    if not result.matches:
        row.check = {"reason": "No approved passage covers this question, so the model was not asked.",
                     "terms": result.terms, "best_score": result.score}
        return _finish(row, actor, save)

    given = {f"P{i}": m for i, m in enumerate(result.matches, start=1)}
    template = prompts.load("ask_bot")
    system, user = template.render(
        organization=db.session.scalar(select(Organization.name)) or "the company", role=employee.job_role.name,
        experience_level=(employee.experience_level or "Beginner").lower(), question=question,
        passages="\n\n".join(f"[{label}] {p['doc_id']} section {p['section_id']}\n{p['text']}" for label, p in given.items()))
    try:
        provider = provider or build_provider(app_config)
        call = call_structured(provider, model_names(app_config, "module"), system, user, BotAnswer)
    except ProviderError as exc:
        call = None
        error = f"{exc.kind}: {exc}"
    row.sources = [{"label": l, "doc_id": p["doc_id"], "section_id": p["section_id"], "text": p["text"][:1200],
                    "requirements": p["requirements"][:4], "score": p["score"], "cited": False} for l, p in given.items()]
    if call is None or not call.ok:
        row.status = "blocked"
        row.check = {"reason": "The model could not be reached, so here are the passages instead.",
                     "error": (call.error if call else error)[:200]}
    else:
        ok, check = check_answer(call.parsed, given)
        cited = [given[l] for l in check["citations"] if l in given]
        for s in row.sources:
            s["cited"] = s["label"] in check["citations"]
        conflicts = _open_conflicts([pk for p in cited for pk in p["requirement_pks"]])
        if conflicts:
            check["open_conflicts"] = conflicts
        row.check = check
        if ok:
            row.status, row.answer = "answered", call.parsed.answer[: c["max_answer_chars"]]
        elif not call.parsed.answerable:
            row.status = "no_source"
        else:
            row.status = "blocked"
    if save and call is not None:
        run = GenerationRun(plan_id=None, phase="ask", provider="gemini", model=call.model or "", params={},
                            prompt_template=template.name, prompt_version=template.version,
                            prompt_sha256=template.sha256, system_prompt=system, user_prompt=user,
                            source_versions=sorted({p["doc_id"] for p in given.values()}), raw_response=call.raw,
                            parsed_ok=call.ok, schema_errors=call.schema_errors, attempts=call.attempts,
                            error=call.error or None, latency_ms=call.latency_ms, tokens_in=call.tokens_in,
                            tokens_out=call.tokens_out)
        db.session.add(run)
        db.session.flush()
        row.run_id = run.id
    return _finish(row, actor, save)


def _finish(row, actor, save):
    if save:
        db.session.add(row)
        db.session.flush()
        audit.record(f"bot.{row.status}", "bot_question", str(row.id), actor=actor,
                     detail={"score": row.score, "sources": [s["doc_id"] for s in row.sources if s.get("cited")]},
                     commit=False)
        db.session.commit()
    return row


def escalate(row, actor):
    employee = row.employee
    if not employee.reporting_manager_code:
        return False
    row.status, row.manager_code, row.escalated_at = "escalated", employee.reporting_manager_code, utcnow()
    audit.record("bot.escalated", "bot_question", str(row.id), actor=actor,
                 detail={"manager": row.manager_code}, commit=False)
    db.session.commit()
    return True


def manager_reply(row, text, actor):
    row.status, row.manager_answer = "manager_answered", " ".join(text.split())[:2000]
    row.answered_by, row.answered_at = actor.get("email"), utcnow()
    audit.record("bot.manager_answered", "bot_question", str(row.id), actor=actor, commit=False)
    db.session.commit()


def feedback(row, helpful, actor):
    row.helpful = helpful
    audit.record("bot.feedback", "bot_question", str(row.id), actor=actor, detail={"helpful": helpful}, commit=False)
    db.session.commit()


def team_questions(manager_code):
    return db.session.scalars(select(BotQuestion).where(BotQuestion.manager_code == manager_code)
                              .order_by(BotQuestion.status != "escalated", BotQuestion.escalated_at.desc())).all()
