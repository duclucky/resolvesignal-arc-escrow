"""Render public output from checked declarations rather than model-authored prose."""

from .compiler import case_completes, case_resolves, supporting, validate_bound_review


def render_result(decision, *, call_id: str, profile: dict):
    request, action, draft = validate_bound_review(decision)
    observation = supporting(request, action)
    outcomes = []
    for case in sorted(observation.cases, key=lambda row: row.id):
        resolved = case_resolves(request.objective.success_contract, case)
        outcomes.append({
            "case_id": case.id,
            "completion_if_verified": "proven" if case_completes(case) else "not_proven",
            "goal_resolution_if_verified": "proven" if resolved else "not_proven",
            "next": "stop" if resolved else "blocked",
        })
    proposal_review = {}
    if request.proposed_action_id is not None:
        proposal_review["proposal_review"] = {
            "status": "retain" if request.proposed_action_id == action.id else "replace",
            "proposed_action_id": request.proposed_action_id,
            "selected_action_id": action.id,
            "proposed_action_admissible": request.proposed_action_id in decision.contract.candidate_ids,
            "basis": "independent_validated_selection",
            "execution_authorized": False,
            "limitations": (
                "Agreement with a separately selected conditional action, not proof of optimality "
                "or real-world success. A replacement does not by itself establish that the proposal was unsafe."
            ),
        }
    return {
        "call_id": call_id,
        "input_sha256": decision.contract.input_sha256,
        "service": {"outcome": "result_ready", "deliverable": "one_conditional_next_action"},
        "scope": {
            "business_action_executed_by_service": False,
            "external_evidence_independently_verified": False,
            "real_world_goal_state": "not_observed",
        },
        "decision": {
            **proposal_review,
            "action_id": action.id,
            "parameters": {argument.name: argument.value for argument in action.arguments} if isinstance(action.arguments, list) else {},
            "target_id": action.target_id,
            "effect": action.effect,
            "reason": draft.model_dump(exclude={"action_id"}),
            "success_contract": request.objective.success_contract.model_dump(),
            "response_observation_ref": observation.id,
            "conditional_outcomes": outcomes,
            "pre_execution": {
                "authority": "must_verify",
                "target_freshness": "must_verify",
                "on_unverified": "do_not_execute",
            },
        },
        "assurance": {
            "structural_checks": "passed",
            "semantic_checks": "supported",
            "semantic_certainty": "not_guaranteed",
            "authority_basis": "caller_declaration",
        },
        "profile": profile,
    }
