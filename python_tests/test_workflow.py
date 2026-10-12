import asyncio
from copy import deepcopy

import pytest
from test_pipeline import FakeGPT, FakeJev

from resolvesignal_pipeline import DecisionFailure, DecisionPipeline
from resolvesignal_pipeline.workflow import (
    PaymentQuote,
    ResolveSignalWorkflow,
    WorkflowError,
)


class FakePayment:
    def __init__(self):
        self.quoted = []
        self.verified = []
        self.completed = []
        self.refunded = []

    async def quote(self, *, call_id, payer, input_sha256):
        quote = PaymentQuote(
            call_id=call_id,
            payer=payer,
            amount_atomic=60_000,
            network="eip155:5042",
            asset="0x3600000000000000000000000000000000000000",
            pay_to=f"vault-{call_id}",
            expires_at=2_000_000_000,
        )
        self.quoted.append((quote, input_sha256))
        return quote

    async def verify(self, quote, proof):
        self.verified.append((quote.call_id, proof))
        return {"transaction": f"payment-{quote.call_id}"}

    async def complete(self, quote, result_sha256):
        self.completed.append((quote.call_id, result_sha256))
        return {"transaction": f"complete-{quote.call_id}"}

    async def refund(self, quote, reason):
        self.refunded.append((quote.call_id, reason))
        return {"transaction": f"refund-{quote.call_id}"}


class SlowGPT(FakeGPT):
    async def plan(self, contract):
        await asyncio.sleep(0.05)
        return await super().plan(contract)


class BlockingPayment(FakePayment):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def quote(self, **kwargs):
        self.started.set()
        await self.release.wait()
        return await super().quote(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["pending", "quoted", "terminal"])
async def test_key_rejects_changed_payload_at_every_phase(request_payload, phase):
    payment = BlockingPayment()
    workflow = ResolveSignalWorkflow(
        pipeline=DecisionPipeline(jev=FakeJev(), gpt=FakeGPT()), payment=payment,
    )
    first = asyncio.create_task(
        workflow.submit(request_payload, payer="0xbuyer", request_key="bound-key")
    )
    await payment.started.wait()
    if phase != "pending":
        payment.release.set()
        order = await first
        if phase == "terminal":
            delivery = await workflow.pay_and_process(order.call_id, payment_proof={})
            await delivery.acknowledge()
    changed = deepcopy(request_payload)
    changed["current_state"]["content"] = "Different invoice evidence."
    try:
        with pytest.raises(WorkflowError) as caught:
            await asyncio.wait_for(
                workflow.submit(changed, payer="0xbuyer", request_key="bound-key"),
                timeout=0.2,
            )
        assert caught.value.code == "idempotency_payload_mismatch"
    finally:
        payment.release.set()
        await first
    assert len(payment.quoted) == 1


@pytest.mark.asyncio
async def test_reordered_keys_are_the_same_request(request_payload):
    payment = FakePayment()
    workflow = ResolveSignalWorkflow(
        pipeline=DecisionPipeline(jev=FakeJev(), gpt=FakeGPT()), payment=payment,
    )
    order = await workflow.submit(request_payload, payer="0xbuyer", request_key="canonical-key")
    reordered = dict(reversed(list(request_payload.items())))
    replay = await workflow.submit(reordered, payer="0xbuyer", request_key="canonical-key")
    assert replay.call_id == order.call_id
    assert len(payment.quoted) == 1


@pytest.mark.asyncio
async def test_key_rejects_another_payer_after_terminal(request_payload):
    payment = FakePayment()
    workflow = ResolveSignalWorkflow(
        pipeline=DecisionPipeline(jev=FakeJev(), gpt=FakeGPT()), payment=payment,
    )
    order = await workflow.submit(request_payload, payer="0xbuyer", request_key="payer-key")
    delivery = await workflow.pay_and_process(order.call_id, payment_proof={})
    await delivery.acknowledge()
    with pytest.raises(WorkflowError, match="idempotency_payer_mismatch"):
        await workflow.submit(request_payload, payer="0xother", request_key="payer-key")
    assert len(payment.quoted) == 1


@pytest.mark.asyncio
async def test_unknown_settlement_is_not_recorded_as_terminal(request_payload):
    class UnknownSettlement(FakePayment):
        async def complete(self, quote, result_sha256):
            raise TimeoutError("confirmation unavailable")

    payment = UnknownSettlement()
    workflow = ResolveSignalWorkflow(
        pipeline=DecisionPipeline(jev=FakeJev(), gpt=FakeGPT()), payment=payment,
    )
    order = await workflow.submit(request_payload, payer="0xbuyer", request_key="unknown-key")
    delivery = await workflow.pay_and_process(order.call_id, payment_proof={})
    with pytest.raises(TimeoutError):
        await delivery.acknowledge()
    with pytest.raises(WorkflowError, match="receipt_not_found"):
        workflow.receipt(order.call_id)
    assert payment.refunded == []
    assert workflow.has_sensitive_context(order.call_id)


@pytest.mark.asyncio
async def test_quote_is_created_only_after_structural_and_jev_admission(request_payload):
    payment = FakePayment()
    rejected = ResolveSignalWorkflow(
        pipeline=DecisionPipeline(jev=FakeJev(False), gpt=FakeGPT()),
        payment=payment,
    )

    with pytest.raises(DecisionFailure):
        await rejected.submit(request_payload, payer="0xbuyer", request_key="key-reject")
    assert payment.quoted == []

    accepted = ResolveSignalWorkflow(
        pipeline=DecisionPipeline(jev=FakeJev(), gpt=FakeGPT()),
        payment=payment,
    )
    order = await accepted.submit(request_payload, payer="0xbuyer", request_key="key-ok")
    assert order.status == "quoted"
    assert order.quote.amount_atomic == 60_000


@pytest.mark.asyncio
async def test_paid_success_is_completed_only_after_delivery_ack_and_then_purged(request_payload):
    payment = FakePayment()
    workflow = ResolveSignalWorkflow(
        pipeline=DecisionPipeline(jev=FakeJev(), gpt=FakeGPT()),
        payment=payment,
    )
    order = await workflow.submit(request_payload, payer="0xbuyer", request_key="key-success")
    delivery = await workflow.pay_and_process(order.call_id, payment_proof={"signed": "x402"})

    assert delivery.status == "result_ready"
    assert payment.completed == []
    assert workflow.has_sensitive_context(order.call_id)

    receipt = await delivery.acknowledge()
    assert receipt.status == "completed"
    assert payment.completed[0][0] == order.call_id
    assert not workflow.has_sensitive_context(order.call_id)
    assert workflow.receipt(order.call_id).result is None


@pytest.mark.asyncio
async def test_delivery_failure_refunds_and_purges(request_payload):
    payment = FakePayment()
    workflow = ResolveSignalWorkflow(
        pipeline=DecisionPipeline(jev=FakeJev(), gpt=FakeGPT()),
        payment=payment,
    )
    order = await workflow.submit(request_payload, payer="0xbuyer", request_key="key-delivery")
    delivery = await workflow.pay_and_process(order.call_id, payment_proof={"signed": "x402"})

    receipt = await delivery.fail("response_not_delivered")
    assert receipt.status == "refunded"
    assert payment.refunded == [(order.call_id, "response_not_delivered")]
    assert not workflow.has_sensitive_context(order.call_id)


@pytest.mark.asyncio
async def test_quality_failure_after_payment_refunds_without_returning_draft(request_payload):
    invalid = FakeGPT().ir.model_copy(update={"action_id": "invented"})
    payment = FakePayment()
    workflow = ResolveSignalWorkflow(
        pipeline=DecisionPipeline(jev=FakeJev(), gpt=FakeGPT(ir=invalid)),
        payment=payment,
    )
    order = await workflow.submit(request_payload, payer="0xbuyer", request_key="key-quality")

    with pytest.raises(WorkflowError) as caught:
        await workflow.pay_and_process(order.call_id, payment_proof={"signed": "x402"})

    assert caught.value.code == "service_failed_refunded"
    receipt = workflow.receipt(order.call_id)
    assert receipt.status == "refunded"
    assert receipt.result is None
    assert payment.refunded[0][0] == order.call_id
    assert not workflow.has_sensitive_context(order.call_id)


@pytest.mark.asyncio
async def test_processing_deadline_refunds_without_returning_draft(request_payload):
    payment = FakePayment()
    workflow = ResolveSignalWorkflow(
        pipeline=DecisionPipeline(jev=FakeJev(), gpt=SlowGPT()),
        payment=payment,
        processing_timeout_seconds=0.01,
    )
    order = await workflow.submit(
        request_payload, payer="0xbuyer", request_key="key-timeout"
    )

    with pytest.raises(WorkflowError) as caught:
        await workflow.pay_and_process(order.call_id, payment_proof={"signed": "x402"})

    assert caught.value.code == "service_failed_refunded"
    assert workflow.receipt(order.call_id).failure_code == "response_deadline_exceeded"
    assert workflow.receipt(order.call_id).result is None
    assert payment.refunded == [(order.call_id, "response_deadline_exceeded")]


@pytest.mark.asyncio
async def test_idempotency_and_concurrent_orders_do_not_mix_results(request_payload):
    payment = FakePayment()
    workflow = ResolveSignalWorkflow(
        pipeline=DecisionPipeline(jev=FakeJev(), gpt=FakeGPT()),
        payment=payment,
        max_concurrency=10,
    )
    first, replay = await asyncio.gather(
        workflow.submit(request_payload, payer="0xbuyer", request_key="same-key"),
        workflow.submit(request_payload, payer="0xbuyer", request_key="same-key"),
    )
    assert first.call_id == replay.call_id
    assert len(payment.quoted) == 1

    orders = await asyncio.gather(*(
        workflow.submit(request_payload, payer=f"0xbuyer{i}", request_key=f"key-{i}")
        for i in range(5)
    ))
    deliveries = await asyncio.gather(*(
        workflow.pay_and_process(order.call_id, payment_proof={"order": order.call_id})
        for order in orders
    ))
    assert [delivery.result["call_id"] for delivery in deliveries] == [order.call_id for order in orders]
    assert [delivery.quote.payer for delivery in deliveries] == [f"0xbuyer{i}" for i in range(5)]
