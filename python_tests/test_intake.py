from copy import deepcopy

import pytest
from pydantic import ValidationError

from resolvesignal_pipeline import form_document, normalize_request


def test_complete_request_is_canonicalized(request_payload):
    first = normalize_request(request_payload)
    reordered = dict(reversed(list(deepcopy(request_payload).items())))
    second = normalize_request(reordered)

    assert first.canonical_json == second.canonical_json
    assert first.input_sha256 == second.input_sha256


def test_blank_nested_text_is_rejected(request_payload):
    request_payload["observations"][0]["explanation"] = "   "

    with pytest.raises(ValidationError):
        normalize_request(request_payload)


def test_absence_must_be_explicit_and_explained(request_payload):
    request_payload["previous_attempts"] = {
        "status": "none",
        "content": "No previous attempts were made.",
    }
    normalized = normalize_request(request_payload)
    assert normalized.request.previous_attempts.status == "none"

    request_payload["previous_attempts"]["content"] = ""
    with pytest.raises(ValidationError):
        normalize_request(request_payload)


def test_invalid_cross_reference_is_rejected(request_payload):
    request_payload["policy"]["conditions"][0]["observation_id"] = "missing"

    with pytest.raises(ValidationError):
        normalize_request(request_payload)


def test_machine_form_exposes_complete_schema_and_failure_policy():
    form = form_document()
    required = set(form["request_schema"]["required"])

    assert {"objective", "current_state", "observations", "policy", "capabilities"} <= required
    assert form["required_behavior"]["all_fields_required"] is False
    assert form["required_behavior"]["optional_fields"] == ["proposed_action_id"]
    assert "proposed_action_id" not in required
    assert form["required_behavior"]["post_payment_questions"] is False
    assert form["failure_policy"]["after_payment"] == "withhold_invalid_output_and_refund"
