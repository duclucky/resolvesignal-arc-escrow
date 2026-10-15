"""Pure compiler and fail-closed validation for model-selected decisions."""

import hashlib
import hmac
from dataclasses import dataclass
from decimal import Decimal

from .contracts import (
    Action,
    DecisionIR,
    Request,
    SemanticCheck,
    SemanticReview,
    SemanticVerdict,
    SourceBinding,
)
from .intake import canonical


class ContractError(Exception):
    def __init__(self, code: str, **details):
        self.code = code
        self.details = details
        super().__init__(code)


def case_completes(case) -> bool:
    return case.operation_completed and case.evidence in {"usable", "authoritative_absence"} and case.target == "matched"


def case_resolves(success_contract, case) -> bool:
    required = {criterion.id for criterion in success_contract.criteria}
    return (
        case_completes(case)
        and (not success_contract.requires_final_state or case.finality == "final")
        and required <= set(case.satisfies)
    )


def supporting(request: Request, action: Action):
    rows = action.response_observations if isinstance(action.response_observations, list) else []
    return next(
        (
            observation
            for observation in rows
            if observation.kind == "problem_state"
            and any(case_resolves(request.objective.success_contract, case) for case in observation.cases)
        ),
        None,
    )


def json_equal(left, right) -> str:
    if type(left) in (int, float) and type(right) in (int, float):
        return "true" if Decimal(str(left)) == Decimal(str(right)) else "false"
    if type(left) is not type(right):
        return "unknown"
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return "false"
        children = [json_equal(left[key], right[key]) for key in left]
    elif isinstance(left, list):
        if len(left) != len(right):
            return "false"
        children = [json_equal(a, b) for a, b in zip(left, right, strict=True)]
    else:
        return "true" if left == right else "false"
    return "false" if "false" in children else "unknown" if "unknown" in children else "true"


def condition_truth(condition, observation) -> str:
    if observation.status != "provided":
        return "unknown"
    if condition.operator == "exists":
        return "true"
    left, right = observation.value, condition.expected
    if condition.operator in {"eq", "ne"}:
        equal = json_equal(left, right)
        return equal if condition.operator == "eq" else {"true": "false", "false": "true", "unknown": "unknown"}[equal]
    if type(left) not in (int, float) or type(right) not in (int, float):
        return "unknown"
    left, right = Decimal(str(left)), Decimal(str(right))
    return "true" if {
        "gt": left > right,
        "gte": left >= right,
        "lt": left < right,
        "lte": left <= right,
    }[condition.operator] else "false"


@dataclass(frozen=True)
class CompiledContract:
    request_json: str
    input_sha256: str
    candidate_ids: tuple[str, ...]

    def request(self) -> Request:
        return Request.model_validate_json(self.request_json)


def compile_contract(normalized) -> CompiledContract:
    request = normalized.request
    observations = {observation.id: observation for observation in request.observations}
    candidates = []
    actions = request.capabilities if isinstance(request.capabilities, list) else []
    for action in actions:
        if (
            action.id not in request.policy.allowed_action_ids
            or action.id in request.policy.forbidden_action_ids
            or action.target_id != request.objective.target_id
            or action.effect not in {"read_only", "state_change"}
            or action.requires_approval
            or supporting(request, action) is None
        ):
            continue
        guards = [condition for condition in request.policy.conditions if not condition.action_ids or action.id in condition.action_ids]
        if all(condition_truth(condition, observations[condition.observation_id]) == "true" for condition in guards):
            candidates.append(action.id)
    if not candidates or request.policy.authority.status != "provided":
        raise ContractError("no_admissible_action")
    return CompiledContract(normalized.canonical_json, normalized.input_sha256, tuple(sorted(candidates)))


def check_ir(contract: CompiledContract, draft: DecisionIR):
    request = contract.request()
    if draft.action_id not in contract.candidate_ids:
        raise ContractError("action_not_admissible")
    actions = {action.id: action for action in request.capabilities}
    action = actions[draft.action_id]
    observations = {observation.id: observation for observation in request.observations}
    goals = {criterion.id for criterion in request.objective.success_contract.criteria}
    constraints = {"authority", "constraints"} | {condition.id for condition in request.policy.conditions}
    for references, allowed in (
        (draft.evidence_refs, set(observations)),
        (draft.goal_refs, goals),
        (draft.constraint_refs, constraints),
    ):
        if len(set(references)) != len(references) or not set(references) <= allowed:
            raise ContractError("invalid_ir_reference")
    applicable = {"authority", "constraints"} | {
        condition.id
        for condition in request.policy.conditions
        if not condition.action_ids or action.id in condition.action_ids
    }
    if set(draft.goal_refs) != goals or not applicable <= set(draft.constraint_refs):
        raise ContractError("ir_coverage_incomplete")
    if any(observations[reference].target_id != request.objective.target_id for reference in draft.evidence_refs):
        raise ContractError("evidence_target_mismatch")
    if draft.reason_kind == "obtain_goal_evidence" and action.effect != "read_only":
        raise ContractError("reason_effect_mismatch")
    if draft.reason_kind == "achieve_declared_goal" and action.effect != "state_change":
        raise ContractError("reason_effect_mismatch")
    if draft.reason_kind == "lower_declared_cost":
        other = actions.get(draft.comparison.other_action_id) if draft.comparison else None
        facts = {fact.id: fact for fact in request.facts} if isinstance(request.facts, list) else {}
        selected = facts.get(action.cost_fact_id)
        compared = facts.get(other.cost_fact_id) if other else None
        if (
            not other
            or other.id == action.id
            or other.id not in contract.candidate_ids
            or not selected
            or not compared
            or selected.unit != compared.unit
            or not Decimal(selected.value) < Decimal(compared.value)
        ):
            raise ContractError("invalid_cost_comparison")
    elif draft.comparison is not None:
        raise ContractError("unexpected_comparison")
    return request, action


def semantic_sources(request: Request, action: Action):
    sources = {
        "objective": request.objective.statement,
        "capability": action.description,
        "authority": request.policy.authority.content,
        "constraints": request.policy.constraints.content,
    }
    sources.update({
        f"observation.{observation.id}": canonical({
            "status": observation.status,
            "value": observation.value,
            "explanation": observation.explanation,
            "source": observation.source,
        })
        for observation in request.observations
    })
    sources.update({f"goal.{criterion.id}": criterion.description for criterion in request.objective.success_contract.criteria})
    sources.update({f"condition.{condition.id}": canonical(condition.model_dump()) for condition in request.policy.conditions})
    rows = action.response_observations if isinstance(action.response_observations, list) else []
    sources.update({f"response.{observation.id}": canonical(observation.model_dump()) for observation in rows})
    return sources


def claim_sources(draft: DecisionIR, request: Request, action: Action):
    return {
        "action_fit": {"objective", "capability"},
        "evidence_relevance": {f"observation.{reference}" for reference in draft.evidence_refs},
        "constraint_alignment": {"authority", "constraints"} | {
            f"condition.{reference}" for reference in draft.constraint_refs if reference not in {"authority", "constraints"}
        },
        "goal_alignment": {f"goal.{reference}" for reference in draft.goal_refs} | {f"response.{supporting(request, action).id}"},
    }


def review_packet(contract: CompiledContract, draft: DecisionIR):
    request, action = check_ir(contract, draft)
    return {
        "request": request.model_input(),
        "decision_ir": draft.model_dump(mode="json"),
        "claims": {key: sorted(value) for key, value in claim_sources(draft, request, action).items()},
        "sources": semantic_sources(request, action),
    }


@dataclass(frozen=True)
class ValidatedDecision:
    contract: CompiledContract
    ir_json: str
    review_json: str


def _review_rows(review, claims):
    rows = {check.claim_id: check for check in review.checks}
    if len(rows) != len(review.checks) or set(rows) != set(claims):
        raise ContractError("semantic_coverage_invalid")
    return rows


def _sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def validate_decision(contract: CompiledContract, draft: DecisionIR, verdict: SemanticVerdict):
    request, action = check_ir(contract, draft)
    sources = semantic_sources(request, action)
    claims = claim_sources(draft, request, action)
    rows = _review_rows(verdict, claims)
    checks = []
    for claim_id, required_sources in claims.items():
        check = rows[claim_id]
        if check.verdict != "supported":
            raise ContractError("semantic_check_failed", claim_id=claim_id, verdict=check.verdict)
        checks.append(SemanticCheck(
            claim_id=claim_id,
            verdict=check.verdict,
            source_bindings=[
                SourceBinding(source_ref=reference, source_sha256=_sha256(sources[reference]))
                for reference in sorted(required_sources)
            ],
        ))
    return ValidatedDecision(contract, canonical(draft.model_dump()), canonical(SemanticReview(checks=checks).model_dump()))


def validate_bound_review(decision: ValidatedDecision):
    draft = DecisionIR.model_validate_json(decision.ir_json)
    review = SemanticReview.model_validate_json(decision.review_json)
    request, action = check_ir(decision.contract, draft)
    sources = semantic_sources(request, action)
    claims = claim_sources(draft, request, action)
    rows = _review_rows(review, claims)
    for claim_id, required_sources in claims.items():
        check = rows[claim_id]
        references = [binding.source_ref for binding in check.source_bindings]
        if len(references) != len(set(references)) or set(references) != required_sources:
            raise ContractError("semantic_citation_invalid", claim_id=claim_id)
        for binding in check.source_bindings:
            source = sources.get(binding.source_ref)
            if source is None or not hmac.compare_digest(binding.source_sha256, _sha256(source)):
                raise ContractError("semantic_citation_invalid", claim_id=claim_id)
        if check.verdict != "supported":
            raise ContractError("semantic_check_failed", claim_id=claim_id, verdict=check.verdict)
    return request, action, draft
