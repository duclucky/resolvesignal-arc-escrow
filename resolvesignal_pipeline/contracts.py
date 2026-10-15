"""Public request and decision contracts used by the production pipeline."""

import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Answer(StrictModel):
    status: Literal["provided", "none", "unknown"]
    content: Text

    @model_validator(mode="after")
    def meaningful(self):
        markers = {"none", "n/a", "unknown", "không có", "không biết", "-"}
        if self.status == "provided" and self.content.casefold() in markers:
            raise ValueError("Use none/unknown status and explain the absence")
        return self


class Absent(StrictModel):
    status: Literal["none"]
    explanation: Text


class SuccessCriterion(StrictModel):
    id: Identifier
    description: Text
    allow_authoritative_absence: bool = Field(strict=True)


class SuccessContract(StrictModel):
    requires_final_state: bool = Field(strict=True)
    criteria: Annotated[list[SuccessCriterion], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_criteria(self):
        if len({criterion.id for criterion in self.criteria}) != len(self.criteria):
            raise ValueError("duplicate success criterion ID")
        return self


class ResponseCase(StrictModel):
    id: Identifier
    description: Text
    evidence: Literal["usable", "authoritative_absence", "unavailable"]
    target: Literal["matched", "mismatched", "unverified"]
    finality: Literal["final", "non_final", "unknown"]
    operation_completed: bool = Field(strict=True)
    satisfies: list[Identifier]

    @model_validator(mode="after")
    def proof_is_consistent(self):
        cannot_prove = self.evidence == "unavailable" or self.target != "matched"
        if cannot_prove and (self.operation_completed or self.satisfies):
            raise ValueError("unavailable or mismatched evidence cannot prove an outcome")
        if len(set(self.satisfies)) != len(self.satisfies):
            raise ValueError("duplicate success criterion reference")
        return self


class ResponseObservation(StrictModel):
    id: Identifier
    kind: Literal["acknowledgement", "action_completion", "problem_state"]
    description: Text
    cases: Annotated[list[ResponseCase], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate response case ID")
        return self


class ActionArgument(StrictModel):
    name: Identifier
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class Action(StrictModel):
    id: Identifier
    description: Text
    effect: Literal["read_only", "state_change", "unknown"]
    requires_approval: bool = Field(strict=True)
    target_id: Text
    cost_fact_id: Identifier | None
    arguments: Annotated[list[ActionArgument], Field(min_length=1, max_length=20)] | Absent
    response_observations: Annotated[list[ResponseObservation], Field(min_length=1, max_length=20)] | Absent

    @model_validator(mode="after")
    def unique_members(self):
        if isinstance(self.arguments, list) and len({row.name for row in self.arguments}) != len(self.arguments):
            raise ValueError("duplicate argument name")
        if isinstance(self.response_observations, list) and len({row.id for row in self.response_observations}) != len(self.response_observations):
            raise ValueError("duplicate response observation ID")
        return self


class Fact(StrictModel):
    id: Identifier
    value: Annotated[str, StringConstraints(pattern=r"^-?\d{1,18}(\.\d{1,12})?$")]
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    source: Text


def contains_blank(value):
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return any(contains_blank(child) for child in value)
    if isinstance(value, dict):
        return any(not str(key).strip() or contains_blank(child) for key, child in value.items())
    return False


class Observation(StrictModel):
    id: Identifier
    target_id: Text
    status: Literal["provided", "none", "unknown"]
    value: JsonValue
    explanation: Text
    source: Text

    @model_validator(mode="after")
    def explicit_value(self):
        json.dumps(self.value, allow_nan=False)
        if contains_blank(self.value):
            raise ValueError("observation contains blank text")
        if self.status == "provided" and self.value in (None, "", [], {}):
            raise ValueError("provided observation requires a value")
        if self.status != "provided" and self.value is not None:
            raise ValueError("none/unknown observation must use null and an explanation")
        return self


class Condition(StrictModel):
    id: Identifier
    observation_id: Identifier
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "exists"]
    expected: JsonValue
    action_ids: list[Identifier]


class Objective(StrictModel):
    target_id: Text
    statement: Text
    success_contract: SuccessContract


class Policy(StrictModel):
    authority: Answer
    constraints: Answer
    allowed_action_ids: list[Identifier]
    forbidden_action_ids: list[Identifier]
    conditions: list[Condition]


class Request(StrictModel):
    objective: Objective
    current_state: Answer
    observations: Annotated[list[Observation], Field(min_length=1)]
    policy: Policy
    capabilities: Annotated[list[Action], Field(min_length=1)] | Absent
    facts: Annotated[list[Fact], Field(min_length=1)] | Absent
    previous_attempts: Answer
    observed_at: datetime
    locale: Literal["vi", "en"]
    proposed_action_id: Identifier | None = Field(
        default=None,
        description="Optional declared capability ID. Hidden from model inputs; compared after independent validation. Arguments come from that capability.",
    )

    def model_input(self):
        return self.model_dump(mode="json", exclude={"proposed_action_id"})

    @model_validator(mode="after")
    def bindings(self):
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        if self.current_state.status != "provided":
            raise ValueError("current_state must provide an observable state")
        actions = self.capabilities if isinstance(self.capabilities, list) else []
        action_ids = {action.id for action in actions}
        if self.proposed_action_id is not None and self.proposed_action_id not in action_ids:
            raise ValueError("proposed action must reference a declared capability")
        observations = {observation.id for observation in self.observations}
        facts = {fact.id for fact in self.facts} if isinstance(self.facts, list) else set()
        if len(action_ids) != len(actions) or len(observations) != len(self.observations):
            raise ValueError("duplicate action or observation ID")
        if isinstance(self.facts, list) and len(facts) != len(self.facts):
            raise ValueError("duplicate fact ID")
        conditions = {condition.id for condition in self.policy.conditions}
        if len(conditions) != len(self.policy.conditions):
            raise ValueError("duplicate condition ID")
        for references in (self.policy.allowed_action_ids, self.policy.forbidden_action_ids):
            if len(set(references)) != len(references) or not set(references) <= action_ids:
                raise ValueError("invalid policy action reference")
        goal_ids = {criterion.id for criterion in self.objective.success_contract.criteria}
        absence_ids = {
            criterion.id
            for criterion in self.objective.success_contract.criteria
            if criterion.allow_authoritative_absence
        }
        for condition in self.policy.conditions:
            if condition.id in {"authority", "constraints"}:
                raise ValueError("reserved condition ID")
            if condition.observation_id not in observations or not set(condition.action_ids) <= action_ids:
                raise ValueError("invalid condition reference")
            if contains_blank(condition.expected):
                raise ValueError("condition contains blank text")
        for action in actions:
            if action.cost_fact_id is not None and action.cost_fact_id not in facts:
                raise ValueError("unknown cost fact")
            rows = action.response_observations if isinstance(action.response_observations, list) else []
            for observation in rows:
                for case in observation.cases:
                    if set(case.satisfies) - goal_ids:
                        raise ValueError("unknown success criterion reference")
                    if case.evidence == "authoritative_absence" and set(case.satisfies) - absence_ids:
                        raise ValueError("authoritative absence is not allowed for criterion")
                    if action.effect == "state_change" and case.operation_completed and case.finality != "final":
                        raise ValueError("non-final write cannot prove completion")
        return self


class Comparison(StrictModel):
    other_action_id: Identifier


class DecisionIR(StrictModel):
    action_id: Identifier
    reason_kind: Literal["obtain_goal_evidence", "achieve_declared_goal", "lower_declared_cost"]
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]
    constraint_refs: list[Identifier]
    goal_refs: Annotated[list[Identifier], Field(min_length=1)]
    comparison: Comparison | None


ClaimId = Literal["action_fit", "evidence_relevance", "constraint_alignment", "goal_alignment"]
Verdict = Literal["supported", "unsupported", "uncertain"]


class SemanticVerdictCheck(StrictModel):
    claim_id: ClaimId
    verdict: Verdict


class SemanticVerdict(StrictModel):
    checks: Annotated[list[SemanticVerdictCheck], Field(min_length=4, max_length=4)]


class SourceBinding(StrictModel):
    source_ref: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SemanticCheck(SemanticVerdictCheck):
    source_bindings: Annotated[list[SourceBinding], Field(min_length=1)]


class SemanticReview(StrictModel):
    checks: Annotated[list[SemanticCheck], Field(min_length=4, max_length=4)]
