"""Pydantic models for the two generation phases.

These are passed to Gemini as the response schema, and every response is re-validated here.
Field names follow the SRS (Step 37): requirement IDs, mandatory status, source document and
section, priority, due stage, task and assessment topic.
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from config.loader import load_config

Priority = Literal["High", "Medium", "Low"]
Difficulty = Literal["Beginner", "Intermediate", "Advanced"]
QuizType = Literal["multiple_choice", "multiple_response", "true_false", "scenario"]


def clean_id(value):
    """Formatting only: '[R-GDP-01-004] ' -> 'R-GDP-01-004'. Invented IDs still fail validation later."""
    return value.strip().strip("[]").strip() if isinstance(value, str) else value


class IdField(BaseModel):
    @field_validator("requirement_id", "module_key", check_fields=False)
    @classmethod
    def clean(cls, value):
        return clean_id(value)

    @field_validator("requirement_ids", check_fields=False)
    @classmethod
    def clean_many(cls, value):
        return [clean_id(v) for v in value]


def _stage_codes():
    return {s["code"] for s in load_config("stages")["stages"]}


class StageField(IdField):
    @field_validator("due_stage", "stage", check_fields=False)
    @classmethod
    def known_stage(cls, value):
        if value not in _stage_codes():
            raise ValueError(f"unknown stage '{value}'")
        return value


# --------------------------------------------------------------------------- Phase 1: outline

class OutlineRequirement(StageField):
    requirement_id: str = Field(description="The identifier of the source clause, without brackets")
    mandatory: bool
    priority: Priority
    due_stage: str
    category: str = Field(description="The knowledge area, one of the provided categories")
    source_document_id: str
    source_section_id: str


class PlanOutline(BaseModel):
    """Phase 1 output for one set of source documents. Python groups requirements into modules by category."""
    requirements: list[OutlineRequirement]
    excluded: list[str] = Field(default_factory=list,
                                description="IDs of source requirements judged not to apply to this employee")
    insufficient_information: list[str] = Field(default_factory=list)

    @field_validator("excluded")
    @classmethod
    def clean_excluded(cls, value):
        return [clean_id(v) for v in value]


# --------------------------------------------------------------------------- Phase 2: module content

class SourceRef(BaseModel):
    source_document_id: str
    source_section_id: str


class Objective(IdField):
    text: str
    requirement_ids: list[str]


class ChecklistItem(StageField):
    activity: str
    required: bool
    due_stage: str
    responsible: str
    requirement_id: str
    source_document_id: str
    source_section_id: str


class Task(StageField):
    description: str
    expected_outcome: str
    completion_criteria: str
    difficulty: Difficulty
    due_stage: str
    requirement_id: str
    source_document_id: str
    source_section_id: str


class Scenario(IdField):
    situation: str
    expected_actions: list[str]
    requirement_id: str
    source_document_id: str
    source_section_id: str


class QuizQuestion(IdField):
    type: QuizType
    question: str
    options: list[str]
    correct_options: list[int] = Field(description="Zero-based indexes of the correct options")
    explanation: str
    difficulty: Difficulty
    requirement_id: str
    source_document_id: str
    source_section_id: str


class RubricRow(BaseModel):
    criterion: str
    weight: int
    expected_performance: str
    pass_condition: str


class Assessment(BaseModel):
    type: Literal["knowledge", "practical", "scenario", "role_specific"]
    topic: str
    rubric: list[RubricRow]


class ModuleContent(IdField):
    module_key: str
    title: str
    purpose: str
    learning_objectives: list[Objective]
    key_concepts: list[str]
    required_sources: list[SourceRef]
    estimated_duration_minutes: int
    activities: list[str]
    checklist: list[ChecklistItem]
    tasks: list[Task]
    scenarios: list[Scenario]
    quiz: list[QuizQuestion]
    assessment: Assessment
    completion_criteria: str
