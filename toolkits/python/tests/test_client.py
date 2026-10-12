import json
from pathlib import Path

import httpx
import pytest
from resolvesignal_integration import (
    IntegrationError,
    ResolveSignalClient,
    build_request,
    validate_request,
)

ROOT = Path(__file__).resolve().parents[1]


def split_example():
    profile = json.loads((ROOT / "examples/profile.json").read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / "examples/runtime.json").read_text(encoding="utf-8"))
    request = {**profile, **runtime}
    return request, profile, runtime


def test_profile_and_runtime_build_the_canonical_request():
    expected, profile, runtime = split_example()
    built = build_request(profile, runtime)
    assert built == expected
    validate_request(built)


def test_profile_cannot_override_runtime_or_add_unknown_fields():
    _, profile, runtime = split_example()
    profile["observations"] = runtime["observations"]
    with pytest.raises(IntegrationError, match="profile_fields_invalid"):
        build_request(profile, runtime)


def test_runtime_timestamp_requires_a_real_timezone_qualified_datetime():
    _, profile, runtime = split_example()
    runtime["observed_at"] = "not-a-date"
    with pytest.raises(IntegrationError, match="observed_at_invalid"):
        build_request(profile, runtime)
    runtime["observed_at"] = "2026-10-08T12:00:00"
    with pytest.raises(IntegrationError, match="observed_at_timezone_required"):
        build_request(profile, runtime)


class FakePayment:
    def __init__(self, amount="60000", response_call_id="call_test"):
        self.amount = amount
        self.response_call_id = response_call_id
        self.pay_calls = 0

    def sign_typed_data(self, typed_data, payer):
        assert typed_data["primaryType"] == "QuoteAdmission"
        return "0x" + "11" * 65

    def inspect(self, url, request_key, input_hash):
        assert url.endswith("/pay") and request_key and input_hash
        return {"status": "payable"}

    def pay(self, url, request_key, input_hash, payer, max_fee_usdc):
        self.pay_calls += 1
        return {
            "data": {
                "response": {
                    "call_id": self.response_call_id,
                    "input_hash": input_hash,
                    "result_available": True,
                    "result": {"decision": {"action_id": "check_status"}},
                },
                "payment": {"amount": "$0.06 USDC", "chain": "eip155:5042"},
            }
        }


def api_transport(amount="60000"):
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v2/form":
            return httpx.Response(
                200,
                json={
                    "mode": "live",
                    "protocol_version": "2",
                    "payment_metadata": {
                        "backend": "escrow_v3",
                        "payer_control_proof_required": True,
                    },
                },
            )
        if request.url.path == "/v2/payer-challenge":
            payer = request.headers["X-Payer-Address"]
            return httpx.Response(
                200,
                json={
                    "challenge_token": "challenge",
                    "typed_data": {
                        "domain": {"chainId": 5042},
                        "primaryType": "QuoteAdmission",
                        "message": {
                            "payer": payer,
                            "purpose": "quote_admission_only_no_payment",
                        },
                    },
                },
            )
        if request.url.path == "/v2/requests":
            return httpx.Response(
                402,
                json={
                    "call_id": "call_test",
                    "input_hash": "a" * 64,
                    "quote_until": 2_000_000_000,
                    "payment_allowed": True,
                    "payment_required": {
                        "accepts": [
                            {
                                "scheme": "exact",
                                "network": "eip155:5042",
                                "asset": "0x3600000000000000000000000000000000000000",
                                "amount": amount,
                                "payTo": "0x" + "22" * 20,
                                "resource": "https://resolvesignal.com/v2/requests/call_test/pay",
                            }
                        ]
                    },
                },
            )
        if request.url.path == "/v2/requests/call_test":
            return httpx.Response(
                200,
                json={
                    "call_id": "call_test",
                    "status": "response_sent",
                    "business_data_deleted": True,
                    "escrow": {"state": "completed"},
                },
            )
        raise AssertionError(request.url)

    return httpx.MockTransport(handler)


def test_paid_call_is_single_shot_and_state_omits_business_payload(tmp_path):
    request, _, _ = split_example()
    payment = FakePayment()
    client = ResolveSignalClient(
        "https://resolvesignal.com",
        payment,
        transport=api_transport(),
    )
    state = tmp_path / "recovery.json"
    result = client.call(
        request,
        payer="0x" + "33" * 20,
        max_fee_usdc="0.06",
        recovery_path=state,
        confirm_paid_call=True,
    )
    assert payment.pay_calls == 1
    assert result["result"]["decision"]["action_id"] == "check_status"
    recovery = json.loads(state.read_text(encoding="utf-8"))
    assert recovery["call_id"] == "call_test"
    assert recovery["financial_status"]["escrow"]["state"] == "completed"
    encoded = state.read_text(encoding="utf-8")
    assert "current_state" not in encoded and "observations" not in encoded


def test_fee_cap_stops_before_payment(tmp_path):
    request, _, _ = split_example()
    payment = FakePayment(amount="70000")
    client = ResolveSignalClient(
        "https://resolvesignal.com",
        payment,
        transport=api_transport("70000"),
    )
    with pytest.raises(IntegrationError, match="fee_cap_exceeded"):
        client.call(
            request,
            payer="0x" + "33" * 20,
            max_fee_usdc="0.06",
            recovery_path=tmp_path / "recovery.json",
            confirm_paid_call=True,
        )
    assert payment.pay_calls == 0


def test_paid_call_requires_explicit_confirmation_before_network(tmp_path):
    request, _, _ = split_example()
    payment = FakePayment()

    def no_network(_):
        raise AssertionError("network must not be reached")

    client = ResolveSignalClient(
        "https://resolvesignal.com", payment, transport=httpx.MockTransport(no_network)
    )
    with pytest.raises(IntegrationError, match="paid_call_not_confirmed"):
        client.call(
            request,
            payer="0x" + "33" * 20,
            max_fee_usdc="0.06",
            recovery_path=tmp_path / "recovery.json",
        )
    assert payment.pay_calls == 0


def test_mismatched_paid_result_is_rejected_without_second_payment(tmp_path):
    request, _, _ = split_example()
    payment = FakePayment(response_call_id="call_other")
    client = ResolveSignalClient(
        "https://resolvesignal.com", payment, transport=api_transport()
    )
    with pytest.raises(IntegrationError, match="paid_response_invalid"):
        client.call(
            request,
            payer="0x" + "33" * 20,
            max_fee_usdc="0.06",
            recovery_path=tmp_path / "recovery.json",
            confirm_paid_call=True,
        )
    assert payment.pay_calls == 1


def test_payment_timeout_preserves_recovery_without_a_second_attempt(tmp_path):
    class TimeoutPayment(FakePayment):
        def pay(self, *args):
            self.pay_calls += 1
            raise TimeoutError("payment outcome unknown")

    request, _, _ = split_example()
    payment = TimeoutPayment()
    state = tmp_path / "recovery.json"
    with ResolveSignalClient(
        "https://resolvesignal.com", payment, transport=api_transport(),
    ) as client:
        with pytest.raises(TimeoutError):
            client.call(
                request, payer="0x" + "33" * 20, max_fee_usdc="0.06",
                recovery_path=state, confirm_paid_call=True,
            )
        saved = json.loads(state.read_text(encoding="utf-8"))
        assert saved["payment_attempted"] is True
        assert saved["last_error"] == "TimeoutError"
        assert client.reconcile(state)["call_id"] == saved["call_id"]
    assert payment.pay_calls == 1
    assert "current_state" not in saved and "result" not in saved


def test_dated_evidence_stops_before_payer_proof_or_payment(tmp_path):
    request, _, _ = split_example()
    payment = FakePayment()
    original = api_transport()

    def enforce_freshness(http_request):
        response = original.handle_request(http_request)
        if http_request.url.path == "/v2/form":
            form = response.json()
            form["max_state_age_seconds"] = 60
            return httpx.Response(200, json=form)
        if http_request.url.path == "/v2/payer-challenge":
            raise AssertionError("stale evidence must stop before wallet use")
        return response

    with ResolveSignalClient(
        "https://resolvesignal.com", payment, transport=httpx.MockTransport(enforce_freshness),
    ) as client:
        with pytest.raises(IntegrationError, match="runtime_evidence_stale"):
            client.call(
                request, payer="0x" + "33" * 20, max_fee_usdc="0.06",
                recovery_path=tmp_path / "recovery.json", confirm_paid_call=True,
            )
    assert payment.pay_calls == 0
