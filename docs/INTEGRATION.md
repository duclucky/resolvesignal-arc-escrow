# Integration

## Call the hosted API

Use [toolkits/python](../toolkits/python/README.md) for the MIT Python Integration
Kit, or implement the [hosted developer guide](https://resolvesignal.com/integration/developer.md)
in your language. No model key or caller-side LLM is needed. Circle Agent Wallet
and Arc Portal handle wallet custody, funding and spending limits.

1. Read `GET /health` and `GET /v2/form`; the live form is authoritative for schema,
   backend and payment requirements.
2. Build and validate static policy plus genuine current runtime evidence locally.
3. Request `POST /v2/payer-challenge` with the payer address. Sign the exact
   `QuoteAdmission` EIP-712 challenge and include its token/proof when submitting
   `POST /v2/requests`. This admission signature is not payment authorization.
4. Inspect the returned HTTP 402 quote. Require x402 v2 `exact`, Arc Mainnet
   `eip155:5042`, six-decimal USDC
   `0x3600000000000000000000000000000000000000`, the initialized per-call vault,
   exact call/input binding, expiry and a hard fee cap. Use the quoted fee;
   do not treat the documented 0.06 USDC fee as permanent.
5. Persist recovery metadata before invoking the returned same-origin `/pay`
   resource once. Verify the response's call ID and input hash.
6. On ambiguity, reconcile the existing call using its recovery file. Do not
   create a replacement purchase to discover the original outcome.
7. Recheck local authority and preconditions before mapping the recommendation's
   action ID to an allowlisted handler. The API does not execute business actions.

The kit is a reference client, not a multi-worker payment scheduler. Use unique,
protected recovery files; never overwrite an unresolved call's recovery metadata.

## Embed the decision core

Install the root package with `python -m pip install -e ".[models]"`.
Construct `DecisionPipeline` with your own `JevAdmissionClient` and
`OpenAIDecisionClient`. `prepare` performs admission; `decide` performs analysis.
These calls use your model credentials, independently of the hosted API.

## Build your own paid service

The **in-memory reference** `ResolveSignalWorkflow` accepts a four-operation
`PaymentAdapter`: `quote`, `verify`, `complete` and `refund`. It sequences one
process's admission, payment, computation, delivery and terminal cleanup. It
does not ship a production HTTP server or durable payment runtime.

An HTTP integration acknowledges delivery only after sending the body. An
adapter returns only authoritatively confirmed outcomes and must reconcile
unknown transactions under stable identities. Implement durable intent storage,
worker coordination and chain receipt validation before handling real funds.
See [payment lifecycle](PAYMENT-LIFECYCLE.md), [privacy](PRIVACY.md) and
[threat model](THREAT-MODEL.md). Use the public ABI/manifest for the deployed
version; never infer a new deployment's addresses from an example.

## Related toolkits

[Agent Commitments](https://github.com/duclucky/agent-commitments) adds shared
budget reservations and grant accounting as a separate alpha primitive. Its
direct ResolveSignal/x402 integration and independent security review are
pending. [Toolkits](https://resolvesignal.com/toolkits) shows current availability;
Agent Starter is planned. Neither is an already integrated hosted payment adapter.
