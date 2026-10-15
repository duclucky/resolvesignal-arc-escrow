"""Machine-readable intake document for agents and non-LLM callers."""

from .contracts import Request


def form_document() -> dict:
    return {
        "schema_version": "1.1",
        "request_schema": Request.model_json_schema(),
        "required_behavior": {
            "all_fields_required": False,
            "optional_fields": ["proposed_action_id"],
            "blank_values_allowed": False,
            "explicit_absence": "Use status none/unknown with a non-blank explanation.",
            "post_payment_questions": False,
        },
        "pipeline": [
            "structural_validation",
            "deterministic_admission",
            "jev_semantic_admission",
            "x402_exact_payment",
            "gpt_5_4_typed_planning",
            "gpt_5_4_semantic_review",
            "trusted_source_binding",
            "deterministic_rendering",
            "delivery_acknowledgement",
            "complete_or_refund",
            "terminal_context_purge",
        ],
        "failure_policy": {
            "before_payment": "reject_without_charge",
            "after_payment": "withhold_invalid_output_and_refund",
        },
    }
