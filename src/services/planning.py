"""Plan generation (Pipeline 1) followed by independent validation (Pipeline 2).

Phase 1 runs one Gemini call per group of documents, in parallel: which requirements apply, mandatory
status, priority, stage and knowledge area. Python then groups requirements into modules by knowledge
area (deterministic). Phase 2 writes each module's learning content, in parallel.
Gemini calls run in worker threads; every database write happens in the request thread.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select, update
from sqlalchemy.orm.attributes import set_committed_value

from comparison_engine import compare
from config.loader import load_config
from database import audit, db
from database.models import (Chunk, ComparisonRow, Conflict, Document, Finding, GenerationRun, MatrixRow, MatrixVersion,
                             Organization, Plan, PlanItem, PlanItemRequirement, PlanModule, Requirement,
                             RequirementPrerequisite, ValidationRun)
from genai_pipeline import prompts
from genai_pipeline.client import call_structured
from genai_pipeline.providers import build_provider, model_names
from genai_pipeline.retrieval import build_bundle, employee_brief
from python_validation import ValidationContext, validate
from python_validation.engine import ruleset_hash
from python_validation.statuses import item_statuses, plan_status, requirement_statuses, scores
from schemas import ModuleContent, PlanOutline

ITEM_PREFIX = {"objective": "O", "checklist": "C", "task": "T", "scenario": "S", "quiz_question": "Q", "assessment": "X"}


class Timeline:
    def __init__(self):
        self.steps, self._start = [], time.perf_counter()

    def mark(self, name, started, detail=""):
        self.steps.append({"step": name, "ms": int((time.perf_counter() - started) * 1000), "detail": detail})

    @property
    def total_ms(self):
        return int((time.perf_counter() - self._start) * 1000)


def current_matrix():
    """Latest approved matrix, else the latest draft (validation then flags it)."""
    approved = db.session.scalar(select(MatrixVersion).where(MatrixVersion.status == "approved")
                                 .order_by(MatrixVersion.version_no.desc()))
    return approved or db.session.scalar(select(MatrixVersion).where(MatrixVersion.status == "draft")
                                         .order_by(MatrixVersion.version_no.desc()))


def _organization():
    return db.session.scalar(select(Organization.name)) or "the organisation"


def _run_row(plan, phase, template, system, user, result, bundle, module_key=None, params=None):
    return GenerationRun(
        plan_id=plan.id, phase=phase, module_key=module_key, provider="gemini", model=result.model or "",
        params=params or {}, prompt_template=template.name, prompt_version=template.version,
        prompt_sha256=template.sha256, system_prompt=system, user_prompt=user,
        source_versions=[list(d) for d in bundle.documents], raw_response=result.raw, parsed_ok=result.ok,
        schema_errors=result.schema_errors, attempts=result.attempts, error=result.error or None,
        latency_ms=result.latency_ms, tokens_in=result.tokens_in, tokens_out=result.tokens_out)


# --------------------------------------------------------------------------- Phase 1

def _shards(bundle, max_reqs):
    """Split the source sections into groups of whole documents, each with at most ~max_reqs clauses."""
    by_doc = {}
    for s in bundle.sections:
        by_doc.setdefault(s["header"], []).append(s)
    shards, current, count = [], {}, 0
    for header, sections in by_doc.items():
        n = sum(len(s["req_ids"]) for s in sections)
        if current and count + n > max_reqs:
            shards.append(current)
            current, count = {}, 0
        current[header] = sections
        count += n
    if current:
        shards.append(current)
    return ["\n\n".join(h + "\n" + "\n\n".join(s["text"] for s in secs) for h, secs in shard.items())
            for shard in shards]


def _outline_prompt(employee, sources, part, parts):
    template = prompts.load("plan_outline")
    cfg = load_config("genai")["plan"]
    stages = ", ".join(f"{s['code']}: {s['label']}" for s in load_config("stages")["stages"])
    system, user = template.render(
        organization=_organization(), day1_max_items=cfg["day1_max_items"], part=part, parts=parts,
        employee_json=json.dumps(employee_brief(employee), indent=1), stages=stages,
        categories=", ".join(load_config("extraction")["competencies"]), sources=sources)
    return template, system, user


def run_outline(employee, bundle, provider, models):
    """Phase 1 over all document shards in parallel. Returns (merged outline | None, [(tpl, sys, usr, result)])."""
    cfg = load_config("genai")
    shards = _shards(bundle, cfg["plan"]["outline_shard_requirements"])
    built = [_outline_prompt(employee, text, i, len(shards)) for i, text in enumerate(shards, start=1)]
    with ThreadPoolExecutor(max_workers=max(1, len(built))) as pool:
        results = list(pool.map(lambda p: call_structured(provider, models, p[1], p[2], PlanOutline), built))
    calls = [(tpl, sys_p, usr_p, res) for (tpl, sys_p, usr_p), res in zip(built, results)]
    if not all(r.ok for r in results):
        return None, calls
    merged, seen = {"requirements": [], "excluded": [], "insufficient_information": []}, set()
    for r in results:
        o = r.parsed.model_dump()
        for req in o["requirements"]:
            if req["requirement_id"] not in seen:
                seen.add(req["requirement_id"])
                merged["requirements"].append(req)
        merged["excluded"] += [x for x in o["excluded"] if x not in seen]
        merged["insufficient_information"] += o["insufficient_information"]
    return merged, calls


def compose_modules(requirements, max_modules, min_size):
    """Deterministic module grouping from Gemini's knowledge-area categories.

    One module per category; categories smaller than min_size are merged into the module with the
    nearest stage (the smaller one on a tie, so one module does not absorb everything), and the
    smallest are merged while there are more than max_modules. A merged module is named after its
    largest category and lists every category it holds. Modules are ordered by their earliest stage.
    Returns (modules, requirements with module_key assigned).
    """
    order = {s["code"]: i for i, s in enumerate(load_config("stages")["stages"])}
    groups = {}
    for r in requirements:
        groups.setdefault(r["category"], []).append(r)

    def earliest(reqs):
        return min(order.get(r["due_stage"], 99) for r in reqs)

    merged = sorted(([[cat], reqs] for cat, reqs in groups.items()), key=lambda g: (earliest(g[1]), g[0][0]))
    while len(merged) > 1 and (len(merged) > max_modules or min(len(g[1]) for g in merged) < min_size):
        i = min(range(len(merged)), key=lambda k: len(merged[k][1]))
        cats, reqs = merged.pop(i)
        j = min(range(len(merged)), key=lambda k: (abs(earliest(merged[k][1]) - earliest(reqs)), len(merged[k][1])))
        merged[j] = [merged[j][0] + cats, merged[j][1] + reqs]
    modules, assigned = [], []
    for n, (cats, reqs) in enumerate(sorted(merged, key=lambda g: (earliest(g[1]), g[0][0])), start=1):
        key = f"M{n:02d}"
        stage = min((r["due_stage"] for r in reqs), key=lambda s: order.get(s, 99))
        size = {c: sum(1 for r in reqs if r["category"] == c) for c in cats}
        main = max(cats, key=lambda c: (size[c], -cats.index(c)))
        others = len(cats) - 1
        title = main if not others else f"{main} and {others} related area{'s' if others > 1 else ''}"
        modules.append({"module_key": key, "title": title, "category": main, "categories": cats, "stage": stage})
        assigned += [{**r, "module_key": key} for r in reqs]
    return modules, assigned


# --------------------------------------------------------------------------- Phase 2

def _module_prompt(employee, module, reqs, bundle):
    template = prompts.load("module_content")
    lines = "\n".join(f"- {r['requirement_id']} (mandatory: {'yes' if r['mandatory'] else 'no'}, "
                      f"due: {r['due_stage']})" for r in reqs)
    system, user = template.render(
        organization=_organization(), experience_level=employee.experience_level,
        employee_json=json.dumps(employee_brief(employee), indent=1),
        module_json=json.dumps(module, indent=1), requirements=lines,
        objectives="2 to 4", quiz_questions=f"{min(max(3, len(reqs)), 6)}",
        sources=bundle.subset(r["requirement_id"] for r in reqs))
    return template, system, user


def generate_plan(employee, actor, app_config, provider=None):
    """Generate and validate a plan. Returns the Plan (status 'Failed' with an error if generation failed)."""
    timeline = Timeline()
    matrix = current_matrix()
    if matrix is None:
        raise ValueError("Build a Role Requirement Matrix before generating plans.")
    provider = provider or build_provider(app_config)
    cfg = load_config("genai")
    outline_models, module_models = model_names(app_config, "outline"), model_names(app_config, "module")
    params = {"temperature": cfg["generation"]["temperature"], "thinking_level": cfg["generation"].get("thinking_level")}

    t = time.perf_counter()
    bundle = build_bundle(employee.job_role)
    code = f"P-{employee.employee_code}"
    version = (db.session.scalar(select(func.max(Plan.version)).where(Plan.plan_code == code)) or 0) + 1
    plan = Plan(plan_code=code, version=version, employee=employee, job_role=employee.job_role,
                matrix_version=matrix, status="generating", created_by=(actor or {}).get("email", "system"))
    db.session.add(plan)
    db.session.flush()
    timeline.mark("Retrieve sources", t, f"{len(bundle.chunks)} sections, {len(bundle.requirement_ids)} clauses, "
                                         f"{len(bundle.documents)} documents")

    t = time.perf_counter()
    outline, calls = run_outline(employee, bundle, provider, outline_models)
    for tpl, sys_p, usr_p, res in calls:
        db.session.add(_run_row(plan, "outline", tpl, sys_p, usr_p, res, bundle,
                                params={**params, "models": outline_models}))
    timeline.mark("Gemini outline", t, f"{len(calls)} parallel calls, {sum(len(c[3].attempts) for c in calls)} "
                                       f"attempts, {sum(c[3].tokens_out for c in calls)} output tokens")
    if outline is None:
        error = next(c[3].error for c in calls if not c[3].ok)
        plan.status, plan.error, plan.timeline = "Failed", error, timeline.steps
        audit.record("plan.generation_failed", "plan", code, actor=actor, version=str(version),
                     detail={"error": error}, commit=False)
        db.session.commit()
        return plan

    modules, outline["requirements"] = compose_modules(outline["requirements"], cfg["plan"]["max_modules"],
                                                       cfg["plan"]["min_module_requirements"])
    outline["modules"] = modules
    plan.outline = outline

    t = time.perf_counter()
    reqs_by_module = {}
    for r in outline["requirements"]:
        reqs_by_module.setdefault(r["module_key"], []).append(r)
    jobs = [(m, *_module_prompt(employee, m, reqs_by_module[m["module_key"]], bundle)) for m in modules]
    with ThreadPoolExecutor(max_workers=cfg["generation"]["module_concurrency"]) as pool:
        results = list(pool.map(lambda j: call_structured(provider, module_models, j[2], j[3], ModuleContent), jobs))
    timeline.mark("Gemini modules", t, f"{len(jobs)} modules in parallel, {sum(not r.ok for r in results)} failed")

    t = time.perf_counter()
    _store_modules(plan, jobs, results, bundle, reqs_by_module, {**params, "models": module_models})
    db.session.flush()
    timeline.mark("Store plan", t)

    t = time.perf_counter()
    validation = validate_plan(plan)
    db.session.flush()
    from src.services.review import route_for_review
    route_for_review(plan, validation)
    timeline.mark("Python validation", t, f"{len(validation.findings)} findings, status {plan.status}")
    plan.timeline = timeline.steps + [{"step": "Total", "ms": timeline.total_ms, "detail": ""}]
    for older in db.session.scalars(select(Plan).where(Plan.plan_code == code, Plan.id != plan.id,
                                                       Plan.status != "superseded")):
        older.status = "superseded"             # only the newest version is current
    audit.record("plan.generated", "plan", code, actor=actor, version=str(version),
                 after={"status": plan.status, "coverage": plan.score_coverage, "ms": timeline.total_ms}, commit=False)
    db.session.commit()
    return plan


def _store_modules(plan, jobs, results, bundle, reqs_by_module, params):
    req_rows = _current_requirements()
    for n, ((module, tpl, sys_p, usr_p), result) in enumerate(zip(jobs, results), start=1):
        position = module.get("position", n)
        run = _run_row(plan, "module", tpl, sys_p, usr_p, result, bundle, module_key=module["module_key"], params=params)
        db.session.add(run)
        db.session.flush()
        title = result.parsed.title if result.ok and result.parsed.title else module["title"]
        pm = PlanModule(plan=plan, module_key=module["module_key"], position=position, title=title[:300],
                        category=module["category"][:60], stage=module["stage"], run_id=run.id, content_ok=result.ok)
        db.session.add(pm)
        if not result.ok:
            continue
        c = result.parsed
        pm.purpose, pm.estimated_minutes, pm.completion_criteria = c.purpose, c.estimated_duration_minutes, c.completion_criteria
        pm.key_concepts, pm.activities = c.key_concepts, c.activities
        pm.required_sources = [s.model_dump() for s in c.required_sources]
        pm.assessment_topics = [c.assessment.topic]
        counters = {}

        def add(item_type, content, req_ids, stage=None, difficulty=None, doc=None, section=None):
            counters[item_type] = counters.get(item_type, 0) + 1
            key = f"{plan.plan_code}-v{plan.version}.{pm.module_key}.{ITEM_PREFIX[item_type]}{counters[item_type]:02d}"
            ids = list(dict.fromkeys(req_ids))
            item = PlanItem(module=pm, item_key=key, item_type=item_type, position=sum(counters.values()),
                            stage=stage or pm.stage, difficulty=difficulty, source_doc_id=doc,
                            source_section_id=section, content={**content, "requirement_ids": ids})
            for rid in ids:
                if rid in req_rows:
                    item.requirement_links.append(PlanItemRequirement(requirement_id=req_rows[rid].id))
            db.session.add(item)

        for o in c.learning_objectives:
            add("objective", o.model_dump(), o.requirement_ids)
        for ch in c.checklist:
            add("checklist", ch.model_dump(), [ch.requirement_id], ch.due_stage, None, ch.source_document_id, ch.source_section_id)
        for tk in c.tasks:
            add("task", tk.model_dump(), [tk.requirement_id], tk.due_stage, tk.difficulty, tk.source_document_id, tk.source_section_id)
        for sc in c.scenarios:
            add("scenario", sc.model_dump(), [sc.requirement_id], None, None, sc.source_document_id, sc.source_section_id)
        for q in c.quiz:
            add("quiz_question", q.model_dump(), [q.requirement_id], None, q.difficulty, q.source_document_id, q.source_section_id)
        add("assessment", c.assessment.model_dump(), [r["requirement_id"] for r in reqs_by_module.get(pm.module_key, [])])


def _current_requirements():
    rows = db.session.execute(select(Requirement, Document).join(Document, Requirement.document_id == Document.id)
                              .where(Document.status.in_(["active", "expired"]))).all()
    return {r.req_id: r for r, _ in rows}


# --------------------------------------------------------------------------- selective regeneration

def _nearest_module(modules, req, order):
    """The module for an added requirement: same knowledge area if there is one, else the closest stage."""
    same = [m for m in modules if req["category"] in m.get("categories", [m["category"]])]
    if same:
        return same[0]["module_key"]
    return min(modules, key=lambda m: abs(order.get(m["stage"], 99) - order.get(req["due_stage"], 99)))["module_key"]


def regenerate_modules(plan, module_keys, actor, app_config, reason="", provider=None, add_requirements=(),
                       drop_requirements=()):
    """New plan version: listed modules are regenerated with Gemini, every other module is copied unchanged.

    add_requirements: requirement IDs to add to the outline (values taken from the approved matrix row),
    each placed in the best-fitting module, which is then regenerated too. drop_requirements: IDs to
    remove from the outline (e.g. a clause removed by a policy update). The whole new version is
    re-validated and routed for review; decisions on copied items are carried over.
    """
    timeline = Timeline()
    cfg = load_config("genai")
    matrix = current_matrix()
    provider = provider or build_provider(app_config)
    module_models = model_names(app_config, "module")
    params = {"temperature": cfg["generation"]["temperature"], "thinking_level": cfg["generation"].get("thinking_level"),
              "models": module_models}
    order = {s["code"]: i for i, s in enumerate(load_config("stages")["stages"])}

    t = time.perf_counter()
    employee, bundle = plan.employee, build_bundle(plan.job_role)
    outline = json.loads(json.dumps(plan.outline))
    regen = set(module_keys)
    if drop_requirements:
        dropped = set(drop_requirements)
        regen |= {r["module_key"] for r in outline["requirements"] if r["requirement_id"] in dropped}
        outline["requirements"] = [r for r in outline["requirements"] if r["requirement_id"] not in dropped]
    if add_requirements:
        rows = {req.req_id: (row, req) for row, req in db.session.execute(
            select(MatrixRow, Requirement).join(Requirement, MatrixRow.requirement_id == Requirement.id)
            .where(MatrixRow.matrix_version_id == matrix.id, MatrixRow.job_role_id == plan.job_role_id,
                   Requirement.req_id.in_(list(add_requirements))))}
        present = {r["requirement_id"] for r in outline["requirements"]}
        for rid in add_requirements:
            if rid in present:
                continue
            if rid not in rows:
                raise ValueError(f"{rid} is not in the approved matrix for this role, so it cannot be added.")
            row, req = rows[rid]
            added = {"requirement_id": rid, "mandatory": row.mandatory, "priority": row.priority,
                     "due_stage": row.due_stage, "category": row.competency, "source_document_id": req.doc_id,
                     "source_section_id": req.section_id, "added_by_reviewer": True}
            added["module_key"] = _nearest_module(outline["modules"], added, order)
            outline["requirements"].append(added)
            regen.add(added["module_key"])
    unknown = regen - {m["module_key"] for m in outline["modules"]}
    if unknown:
        raise ValueError(f"Unknown module(s): {', '.join(sorted(unknown))}")

    version = (db.session.scalar(select(func.max(Plan.version)).where(Plan.plan_code == plan.plan_code)) or 0) + 1
    new_plan = Plan(plan_code=plan.plan_code, version=version, parent_plan_id=plan.id, employee=employee,
                    job_role=plan.job_role, matrix_version=matrix, status="generating", outline=outline,
                    created_by=(actor or {}).get("email", "system"))
    db.session.add(new_plan)
    db.session.flush()
    timeline.mark("Retrieve sources", t, f"regenerating {', '.join(sorted(regen)) or 'nothing'}; "
                                         f"{len(plan.modules) - len(regen)} modules copied unchanged")

    reqs_by_module = {}
    for r in outline["requirements"]:
        reqs_by_module.setdefault(r["module_key"], []).append(r)
    t = time.perf_counter()
    jobs = []
    for m in outline["modules"]:
        if m["module_key"] in regen:
            old = next((x for x in plan.modules if x.module_key == m["module_key"]), None)
            module = {**m, "position": old.position if old else len(outline["modules"])}
            jobs.append((module, *_module_prompt(employee, m, reqs_by_module.get(m["module_key"], []), bundle)))
    with ThreadPoolExecutor(max_workers=max(1, cfg["generation"]["module_concurrency"])) as pool:
        results = list(pool.map(lambda j: call_structured(provider, module_models, j[2], j[3], ModuleContent), jobs))
    timeline.mark("Gemini modules", t, f"{len(jobs)} module(s) regenerated, {sum(not r.ok for r in results)} failed")

    t = time.perf_counter()
    keys = _copy_modules(plan, new_plan, skip=regen, relink=_current_rows_for(plan))
    _store_modules(new_plan, jobs, results, bundle, reqs_by_module, params)
    db.session.flush()
    db.session.refresh(new_plan)
    timeline.mark("Store plan", t, f"{len(keys)} items copied")

    t = time.perf_counter()
    validation = validate_plan(new_plan)
    db.session.flush()
    from src.services.review import route_for_review
    route_for_review(new_plan, validation, carry={"plan": plan, "keys": keys})
    timeline.mark("Python validation", t, f"{len(validation.findings)} findings, status {new_plan.status}")
    new_plan.timeline = timeline.steps + [{"step": "Total", "ms": timeline.total_ms, "detail": ""}]
    if any(not r.ok for r in results):
        new_plan.error = next(r.error for r in results if not r.ok)
    plan.status = "superseded"
    audit.record("plan.regenerated", "plan", plan.plan_code, actor=actor, version=str(version), reason=reason or None,
                 before={"version": plan.version}, after={"status": new_plan.status, "coverage": new_plan.score_coverage},
                 detail={"modules": sorted(regen), "added": list(add_requirements), "dropped": list(drop_requirements)},
                 commit=False)
    db.session.commit()
    return new_plan


def _current_rows_for(plan):
    """{requirement row the plan links to: the current row with the same req_id}. After a policy update the
    copied items then point at the new version's clauses, so the next change is traced correctly."""
    linked = {link.requirement_id for m in plan.modules for i in m.items for link in i.requirement_links}
    if not linked:
        return {}
    req_ids = {r.id: r.req_id for r in db.session.scalars(select(Requirement).where(Requirement.id.in_(linked)))}
    current = _current_requirements()
    return {row_id: current[rid].id for row_id, rid in req_ids.items() if rid in current}


def _copy_modules(plan, new_plan, skip, relink=None):
    """Copy unchanged modules and their items into the new version. Returns {old item_key: new item_key}."""
    old_prefix, new_prefix = f"{plan.plan_code}-v{plan.version}.", f"{new_plan.plan_code}-v{new_plan.version}."
    keys = {}
    with db.session.no_autoflush:           # new rows are complete only after their links are copied
        _copy_into(plan, new_plan, skip, old_prefix, new_prefix, keys, relink or {})
    return keys


def _copy_into(plan, new_plan, skip, old_prefix, new_prefix, keys, relink):
    for m in plan.modules:
        if m.module_key in skip:
            continue
        pm = PlanModule(plan=new_plan, module_key=m.module_key, position=m.position, title=m.title,
                        category=m.category, stage=m.stage, purpose=m.purpose, estimated_minutes=m.estimated_minutes,
                        key_concepts=m.key_concepts, required_sources=m.required_sources, activities=m.activities,
                        assessment_topics=m.assessment_topics, completion_criteria=m.completion_criteria,
                        run_id=m.run_id, content_ok=m.content_ok)
        db.session.add(pm)
        for i in m.items:
            suffix = i.item_key[len(old_prefix):] if i.item_key.startswith(old_prefix) else i.item_key
            keys[i.item_key] = new_prefix + suffix
            item = PlanItem(module=pm, item_key=new_prefix + suffix, item_type=i.item_type, position=i.position,
                            stage=i.stage, difficulty=i.difficulty, source_doc_id=i.source_doc_id,
                            source_section_id=i.source_section_id, content=dict(i.content))
            item.requirement_links = [PlanItemRequirement(requirement_id=relink.get(link.requirement_id, link.requirement_id))
                                      for link in i.requirement_links]
            db.session.add(item)


# --------------------------------------------------------------------------- Pipeline 2

def build_context(plan):
    """Plain-data snapshot for the validation rules."""
    brief = employee_brief(plan.employee)
    matrix_rows = db.session.execute(
        select(MatrixRow, Requirement).join(Requirement, MatrixRow.requirement_id == Requirement.id)
        .where(MatrixRow.matrix_version_id == plan.matrix_version_id, MatrixRow.job_role_id == plan.job_role_id)).all()
    matrix = {req.req_id: {"mandatory": row.mandatory, "priority": row.priority, "due_stage": row.due_stage,
                           "stage_source": req.stage_source, "competency": row.competency, "req_type": req.req_type,
                           "assessment_requirement": row.assessment_requirement, "condition": row.condition,
                           "source_doc_id": req.doc_id, "source_section_id": req.section_id,
                           "source_status": row.source_status, "text": req.text}
              for row, req in matrix_rows}
    current = db.session.execute(
        select(Requirement, Document, Chunk).join(Document, Requirement.document_id == Document.id)
        .join(Chunk, Requirement.chunk_id == Chunk.id).where(Document.status.in_(["active", "expired"]))).all()
    requirements = {r.req_id: {"doc_id": r.doc_id, "section_id": r.section_id, "text": r.text, "mandatory": r.mandatory,
                               "doc_status": d.status, "chunk_text": c.source_text} for r, d, c in current}
    sections, doc_status = {}, {}
    for chunk, doc in db.session.execute(select(Chunk, Document).join(Document, Chunk.document_id == Document.id)
                                         .where(Document.status.in_(["active", "expired"]), Document.tier > 0)):
        key = (doc.doc_id, chunk.section_id)
        sections[key] = (sections.get(key, "") + "\n" + chunk.source_text).strip()
        doc_status[doc.doc_id] = doc.status
    ids = {r.id: r.req_id for r, _, _ in current}
    prereqs = [(ids[a], ids[b]) for a, b in db.session.execute(
        select(RequirementPrerequisite.requirement_id, RequirementPrerequisite.prerequisite_id)) if a in ids and b in ids]
    modules = []
    for m in plan.modules:
        items = [{"item_key": i.item_key, "item_type": i.item_type, "stage": i.stage, "difficulty": i.difficulty,
                  "source_doc_id": i.source_doc_id, "source_section_id": i.source_section_id, "content": i.content,
                  "requirement_ids": i.content.get("requirement_ids", [])} for i in m.items]
        module_reqs = [r["requirement_id"] for r in plan.outline.get("requirements", []) if r.get("module_key") == m.module_key]
        modules.append({"module_key": m.module_key, "title": m.title, "category": m.category, "stage": m.stage,
                        "content_ok": m.content_ok, "items": items, "requirement_ids": module_reqs})
    stage_order = {s["code"]: i for i, s in enumerate(load_config("stages")["stages"])}
    conflicts = {}
    for c in db.session.scalars(select(Conflict).where(Conflict.kind == "cross_document")):
        base = {"conflict": c.conflict_code, "explanation": c.explanation, "rule": c.rule_applied}
        if c.status == "manual_review":
            conflicts[c.left.req_id] = {**base, "type": "manual", "other": c.right.req_id}
            conflicts[c.right.req_id] = {**base, "type": "manual", "other": c.left.req_id}
        elif c.winner is not None:
            conflicts[c.loser.req_id] = {**base, "type": "lost", "winner": c.winner.req_id}
            if c.status == "auto_resolved_warning":
                conflicts[c.winner.req_id] = {**base, "type": "safety_override"}
    return ValidationContext(conflicts=conflicts, employee=brief, role_code=plan.job_role.code, outline=plan.outline, modules=modules,
                             matrix=matrix, requirements=requirements, sections=sections, doc_status=doc_status,
                             prerequisites=prereqs, stage_order=stage_order,
                             matrix_approved=plan.matrix_version.status == "approved",
                             day1_max_items=load_config("genai")["plan"]["day1_max_items"])


def validate_plan(plan):
    """Run Pipeline 2, store the validation run, and update the plan's status and scores."""
    ctx = build_context(plan)
    findings, duration = validate(ctx)
    req_status = requirement_statuses(ctx, findings)
    rows = compare(ctx, req_status)
    s = scores(ctx, findings, rows)
    status = plan_status(findings)
    run = ValidationRun(plan_id=plan.id, matrix_version_id=plan.matrix_version_id,
                        matrix_approved=ctx.matrix_approved, ruleset_hash=ruleset_hash(), plan_status=status,
                        scores=s, requirement_statuses=req_status, duration_ms=duration)
    run.findings = [Finding(rule_id=f.rule_id, severity=f.severity, status=f.status, item_key=f.item_key,
                            req_id=f.req_id, message=f.message, evidence=f.evidence) for f in findings]
    run.comparison_rows = [ComparisonRow(**row) for row in rows]
    db.session.add(run)
    statuses = item_statuses(ctx, findings)
    db.session.flush()
    by_status = {}
    for m in plan.modules:
        for item in m.items:
            new = statuses.get(item.item_key, "Verified")
            if item.status != new:
                by_status.setdefault(new, []).append(item.id)
            set_committed_value(item, "status", new)
    for status_value, ids in by_status.items():     # one UPDATE per status, not one per item
        db.session.execute(update(PlanItem).where(PlanItem.id.in_(ids)).values(status=status_value)
                           .execution_options(synchronize_session=False))
    plan.status = status
    plan.score_coverage, plan.score_traceability = s["coverage"], s["traceability"]
    plan.score_traceability_mandatory = s["traceability_mandatory"]
    plan.score_requirement_consistency = s["requirement_consistency"]
    plan.count_missing, plan.count_unsupported = s["missing"], s["unsupported"]
    plan.count_contradictions, plan.count_duplicates = s["contradictions"], s["duplicates"]
    return run


# --------------------------------------------------------------------------- consistency (SRS Steps 44-45)

def _structured_sets(outline):
    reqs = outline.get("requirements", [])
    return {
        "mandatory_requirements": {r["requirement_id"] for r in reqs if r["mandatory"]},
        "sources": {(r["source_document_id"], r["source_section_id"]) for r in reqs},
        "module_categories": {(r["requirement_id"], r["category"]) for r in reqs},
        "due_stages": {(r["requirement_id"], r["due_stage"]) for r in reqs},
    }


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 1.0


def run_consistency(plan, app_config, provider=None):
    """Re-run Phase 1 with identical inputs and compare structured results, never wording."""
    from itertools import combinations
    provider = provider or build_provider(app_config)
    cfg = load_config("genai")
    models = model_names(app_config, "outline")
    bundle = build_bundle(plan.job_role)
    runs = [plan.outline]
    for _ in range(cfg["consistency"]["extra_runs"]):
        outline, calls = run_outline(plan.employee, bundle, provider, models)
        for tpl, sys_p, usr_p, res in calls:
            db.session.add(_run_row(plan, "consistency", tpl, sys_p, usr_p, res, bundle, params={"models": models}))
        if outline is not None:
            runs.append(outline)
    sets = [_structured_sets(r) for r in runs]
    dims = {}
    for name in sets[0]:
        pairs = [_jaccard(a[name], b[name]) for a, b in combinations(sets, 2)]
        dims[name] = round(sum(pairs) / len(pairs), 3) if pairs else None
    all_mandatory = set().union(*(s["mandatory_requirements"] for s in sets))
    differences = [{"requirement_id": r, "mandatory_in_runs": [i for i, s in enumerate(sets) if r in s["mandatory_requirements"]]}
                   for r in sorted(all_mandatory) if not all(r in s["mandatory_requirements"] for s in sets)]
    score = round(100 * sum(v for v in dims.values() if v is not None) / len(dims), 1) if len(sets) > 1 else None
    plan.consistency = {"runs": len(sets), "dimensions": dims, "differences": differences}
    plan.score_generation_consistency = score
    audit.record("plan.consistency_checked", "plan", plan.plan_code, version=str(plan.version),
                 after={"score": score, "runs": len(sets)}, commit=False)
    db.session.commit()
    return plan


# --------------------------------------------------------------------------- plan comparison (SRS Step 60)

def compare_plans(a, b):
    """Structured comparison of two plans: across roles, departments, experience levels or plan versions."""
    def facts(p):
        reqs = {r["requirement_id"]: r for r in p.outline.get("requirements", [])}
        items = [i for m in p.modules for i in m.items]
        docs = sorted({(r.get("source_document_id"), ) for r in reqs.values()})
        return {"reqs": reqs, "mandatory": {k for k, r in reqs.items() if r.get("mandatory")},
                "categories": {m.category for m in p.modules}, "items": items,
                "by_type": {t: sum(1 for i in items if i.item_type == t) for t in ITEM_PREFIX},
                "minutes": sum(m.estimated_minutes or 0 for m in p.modules),
                "documents": sorted({d[0] for d in docs if d[0]})}
    fa, fb = facts(a), facts(b)
    both = set(fa["reqs"]) & set(fb["reqs"])
    stage_diff = sorted(r for r in both if fa["reqs"][r].get("due_stage") != fb["reqs"][r].get("due_stage"))
    mand_diff = sorted(r for r in both if bool(fa["reqs"][r].get("mandatory")) != bool(fb["reqs"][r].get("mandatory")))
    union = set(fa["reqs"]) | set(fb["reqs"])
    return {
        "a": a, "b": b, "fa": fa, "fb": fb,
        "only_a": sorted(set(fa["reqs"]) - set(fb["reqs"])), "only_b": sorted(set(fb["reqs"]) - set(fa["reqs"])),
        "both": sorted(both), "overlap": round(100.0 * len(both) / len(union), 1) if union else 100.0,
        "stage_diff": stage_diff, "mandatory_diff": mand_diff,
        "categories_only_a": sorted(fa["categories"] - fb["categories"]),
        "categories_only_b": sorted(fb["categories"] - fa["categories"]),
        "differences": {
            "Role": (a.job_role.name, b.job_role.name), "Department": (a.employee.department, b.employee.department),
            "Experience": (a.employee.experience_level, b.employee.experience_level),
            "Matrix": (f"v{a.matrix_version.version_no}" if a.matrix_version else "-",
                       f"v{b.matrix_version.version_no}" if b.matrix_version else "-"),
        },
    }
