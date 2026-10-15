"""Independent selection can be compared without exposing a caller preference."""

import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from test_pipeline import FakeGPT, FakeJev, supported_verdict, valid_ir

from resolvesignal_pipeline import DecisionFailure, DecisionPipeline
from resolvesignal_pipeline.compiler import review_packet
from resolvesignal_pipeline.intake import normalize_request
from resolvesignal_pipeline.providers import JevAdmissionClient, OpenAIDecisionClient


@pytest.mark.parametrize("proposal,status", [("retry_capture", "retain"), ("alternative", "replace")])
async def test_proposal_review(request_payload, proposal, status):
    alternate = copy.deepcopy(request_payload["capabilities"][0])
    alternate["id"] = "alternative"
    request_payload["capabilities"].append(alternate)
    request_payload["proposed_action_id"] = proposal
    pipeline = DecisionPipeline(jev=FakeJev(), gpt=FakeGPT())
    prepared = await pipeline.prepare(request_payload)
    result = await pipeline.decide(prepared, call_id="test")
    review = result["decision"]["proposal_review"]
    assert review["status"] == status
    assert review["selected_action_id"] == "retry_capture"
    assert review["proposed_action_admissible"] is (proposal == "retry_capture")
    assert review["execution_authorized"] is False


async def test_unknown_proposal_fails_before_models(request_payload):
    request_payload["proposed_action_id"] = "invented"
    jev = FakeJev()
    with pytest.raises(DecisionFailure) as caught:
        await DecisionPipeline(jev=jev, gpt=FakeGPT()).prepare(request_payload)
    assert caught.value.disposition == "do_not_charge"
    assert not jev.calls


def test_legacy_commitment_unchanged(request_payload):
    original = normalize_request(request_payload)
    request_payload["proposed_action_id"] = None
    assert normalize_request(request_payload).input_sha256 == original.input_sha256
    request_payload["proposed_action_id"] = "retry_capture"
    assert normalize_request(request_payload).input_sha256 != original.input_sha256


async def test_reference_transports_hide_proposal(request_payload):
    request_payload["proposed_action_id"] = "retry_capture"
    contract = (await DecisionPipeline(jev=FakeJev(), gpt=FakeGPT()).prepare(request_payload)).contract
    requests = []

    def respond(request):
        requests.append(json.loads(request.content)["state"])
        return httpx.Response(200, json={"answers": {"decision": {"type": "choice", "choice": "ready", "confidence": 1}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        await JevAdmissionClient(api_key="synthetic", http=http).admit(contract)

    class Planner:
        @property
        def responses(self):
            return self

        async def parse(self, **kwargs):
            requests.append(json.loads(kwargs["input"]))
            output = valid_ir() if len(requests) == 2 else supported_verdict()
            return SimpleNamespace(output_parsed=output, model="synthetic")

    client = OpenAIDecisionClient(client=Planner())
    await client.plan(contract)
    await client.review(contract, valid_ir())
    assert len(requests) == 3
    assert all("proposed_action_id" not in packet["request"] for packet in requests)
    assert "proposed_action_id" not in review_packet(contract, valid_ir())["request"]
