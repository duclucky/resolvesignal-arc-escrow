# ResolveSignal Decision Pipeline

[![pipeline](https://github.com/duclucky/resolvesignal-decision-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/duclucky/resolvesignal-decision-pipeline/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Arc Mainnet](https://img.shields.io/badge/Arc%20Mainnet-5042-4e56b5)](https://explorer.arc.io/address/0xB2b41f3e45AEe1Da3D8756bd087277f1194bf3C7)

ResolveSignal is a fail-closed, pay-per-call decision pipeline for autonomous
agents. A caller submits current evidence, an explicit goal, authority,
constraints, and executable capabilities. The pipeline returns exactly one
typed conditional next action, or fails the service and takes the refund path.

This repository contains the reusable decision core, an **in-memory reference
workflow**, and Arc escrow contracts. The hosted service has a separate runtime;
this checkout is not its complete production deployment. The reference demonstrates:

1. publish a machine-readable form;
2. reject blank, incomplete, stale, contradictory, or unbound input;
3. compile caller declarations into a deterministic decision contract;
4. ask Jev whether that contract is semantically sufficient **before payment**;
5. issue one x402 exact quote bound to one request and payer;
6. verify the payment and isolate the request from concurrent calls;
7. ask GPT-5.4 for a typed `DecisionIR`, never free-form executable prose;
8. check action, evidence, constraints, and goal alignment;
9. bind the accepted review to exact source hashes in trusted code;
10. render the result from declared IDs and parameters;
11. release the fee only after the response body is delivered;
12. refund paid quality, timeout, or delivery failures; and
13. erase request and result context after the terminal receipt is recorded.

The repository does not include credentials, customer payloads, production
databases, signer material, internal hostnames, or private infrastructure state.

## Why this is more than an LLM wrapper

Jev and GPT-5.4 have different bounded roles. They do not vote on arbitrary
prose and the server does not average their confidence scores.

- **Jev admission:** decides whether a structurally valid request is
  semantically sufficient for this service. A rejection occurs before payment.
- **GPT-5.4 planner:** selects one action and returns only typed references to
  caller-declared evidence, goals, constraints, and capabilities.
- **GPT-5.4 checker:** evaluates four fixed relationships: action fit, evidence
  relevance, constraint alignment, and goal alignment.
- **Trusted compiler:** rejects invented or incomplete references and binds each
  supported relationship to exact source hashes.
- **Deterministic renderer:** builds the public result from checked declarations.
  Model-authored prose never becomes an executable instruction.

Both models remain probabilistic. Passing the gates means the result conforms to
the declared contract; it is not a guarantee that the caller's evidence is true
or that a future operation will succeed.

## End-to-end lifecycle

```mermaid
sequenceDiagram
    participant A as Calling agent
    participant I as Intake/compiler
    participant J as Jev
    participant P as x402/Arc vault
    participant G as GPT-5.4
    participant C as Trusted checker

    A->>I: Complete typed form + payer + idempotency key
    I->>I: Schema, bindings, freshness, admissible actions
    I->>J: Semantic admission
    alt incomplete, contradictory, or unsupported
        J-->>A: Reject before payment
    else admitted
        I-->>A: HTTP 402 exact quote for per-call vault
        A->>P: One USDC payment
        P-->>I: Verified receipt bound to call and payer
        I->>G: Typed planning request
        G-->>I: DecisionIR
        I->>G: Four-claim semantic review
        G-->>C: Typed verdict
        C->>C: Validate IDs, coverage, targets, hashes
        alt any paid gate fails or response is not delivered
            C->>P: Refund original payer
            C-->>A: Service failed; no draft returned
        else result body delivered
            C-->>A: One conditional next action
            C->>P: Complete exact fee to treasury
        end
        C->>C: Purge request and result context
    end
```

## Public modules

| Path | Responsibility |
| --- | --- |
| `resolvesignal_pipeline/contracts.py` | Strict request, capability, response-case, IR, and semantic-review contracts |
| `resolvesignal_pipeline/intake.py` | Canonicalization and input commitment |
| `resolvesignal_pipeline/compiler.py` | Candidate filtering, guard evaluation, IR validation, source binding, review verification |
| `resolvesignal_pipeline/providers.py` | Reference Jev SystemOne and OpenAI Responses adapters |
| `resolvesignal_pipeline/pipeline.py` | Pre-payment admission and paid decision boundaries |
| `resolvesignal_pipeline/render.py` | Deterministic public result construction |
| `resolvesignal_pipeline/workflow.py` | Idempotency, bounded concurrency, payment, delivery, refund, terminal cleanup |
| `src/` | Arc x402 per-call escrow contracts |
| `abi/` and `deployments/` | Public contract interfaces and Arc Mainnet manifest |
| `python_tests/` and `test/` | Pipeline, workflow, Solidity, fuzz, regression, and invariant coverage |
| `toolkits/python/` | MIT hosted-API client, schemas, English offline examples and client tests |
| `scripts/build_integration_kit.py` | Reproducible versioned client ZIP and SHA-256 checksums |

## Run the decision core

Requirements: Python 3.12+.

```bash
git clone --recurse-submodules https://github.com/duclucky/resolvesignal-decision-pipeline.git
cd resolvesignal-decision-pipeline
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[models,dev]"
python -m pytest python_tests -q
```

Windows activation:

```powershell
.venv\Scripts\Activate.ps1
```

Copy `.env.example` into your secret manager or local ignored `.env`. Never put
API keys or signer material in source control.

```python
import os

from resolvesignal_pipeline import (
    DecisionPipeline,
    JevAdmissionClient,
    OpenAIDecisionClient,
)

pipeline = DecisionPipeline(
    jev=JevAdmissionClient(api_key=os.environ["TYPESAFE_API_KEY"]),
    gpt=OpenAIDecisionClient(
        api_key=os.environ["OPENAI_API_KEY"],
        model=os.getenv("OPENAI_DECISION_MODEL", "gpt-5.4"),
    ),
)

# Free gates, including Jev admission, occur here.
prepared = await pipeline.prepare(request_payload)

# In a paid service, issue and verify the x402 quote between these calls.
result = await pipeline.decide(prepared, call_id="call_example")
```

Use `ResolveSignalWorkflow` when you also need quote, payment, delivery,
completion/refund, idempotency, concurrency, and terminal cleanup. Its
`PaymentAdapter` interface keeps the decision system independent of wallet or
facilitator custody.

The workflow's keys and receipts live only in one process. Restarting it loses
them. It supplies no durable journal, multi-worker coordination, chain receipt
validator, or production payment adapter. Implement these boundaries before
using it to operate a paid service; see [payment lifecycle](docs/PAYMENT-LIFECYCLE.md).

## Choose your toolkit

- **Call the hosted API:** install the MIT [Python Integration Kit](toolkits/python/README.md)
  for request building, Circle CLI payment and recovery. No caller-side LLM is required.
- **Embed the decision core:** use `resolvesignal_pipeline` with your own model
  credentials and deployment. This does not call the hosted ResolveSignal API.
- **Coordinate agent budgets:** [Agent Commitments](https://github.com/duclucky/agent-commitments)
  is a separate alpha toolkit. Its direct x402 integration is pending.

[Toolkits](https://resolvesignal.com/toolkits) lists availability. Agent Starter
is planned, not a downloadable agent. Wallet custody and spending limits remain
with Circle Agent Wallet and Arc Portal. See [integration](docs/INTEGRATION.md)
for the payer-control challenge and current hosted contract.

## Input contract

Every field is required. “No data” is valid only when declared explicitly with
`status: none` or `status: unknown` and a non-blank explanation. Empty strings,
omitted keys, duplicate IDs, unknown references, and unbound response cases are
rejected before any paid work.

The caller declares:

- objective target and measurable success criteria;
- current observed state and timezone-aware observation time;
- evidence with stable IDs, sources, and target bindings;
- authority and constraints;
- permitted and forbidden action IDs;
- executable capabilities with fixed arguments;
- response cases that distinguish operation completion from goal resolution;
- prior attempts, facts, and locale.

The service does not fetch arbitrary URLs, infer missing capabilities, ask for
more information after payment, or execute the selected business action.

## Arc escrow failure and refund contract

The table below describes the per-call Arc vault workflow.

| Failure point | Customer charged? | Service outcome |
| --- | --- | --- |
| Schema or binding validation | No | Reject with field errors |
| No admissible automatic action | No | Reject |
| Jev unavailable or rejects | No | Reject; no quote |
| Payment cannot be verified | No confirmed charge | Do not process |
| GPT-5.4 planner unavailable/invalid | Yes | Withhold draft and refund |
| Semantic checker unsupported/uncertain | Yes | Withhold draft and refund |
| Trusted validation or source binding fails | Yes | Withhold result and refund |
| Processing deadline expires | Yes | Refund |
| Response body is not delivered | Yes | Refund |
| Response body is delivered | Yes | Release exact fee |

No paid model failure is reported as a completed service.

## Arc Mainnet settlement

| Component | Address |
| --- | --- |
| Factory | [`0xB2b41f3e45AEe1Da3D8756bd087277f1194bf3C7`](https://explorer.arc.io/address/0xB2b41f3e45AEe1Da3D8756bd087277f1194bf3C7) |
| Vault implementation | [`0xdd02Ec2A86CF8b05081bE88DE4C190d0980D067F`](https://explorer.arc.io/address/0xdd02Ec2A86CF8b05081bE88DE4C190d0980D067F) |
| Deployment transaction | [`0x2aaa6bd0c8a6e5455948e6c44346e7cf4f9f60c71c903aea70289100d90e9724`](https://explorer.arc.io/tx/0x2aaa6bd0c8a6e5455948e6c44346e7cf4f9f60c71c903aea70289100d90e9724) |
| USDC | `0x3600000000000000000000000000000000000000` |

Network: Arc Mainnet, chain ID `5042`. Each accepted call receives one
deterministic CREATE2 vault. Standard x402 v2 `exact` clients pay that vault
without a contract-specific buyer signature. The exact fee is completed to
treasury or the vault refunds the bound payer.

## Verification

```bash
python -m pytest python_tests -q
forge fmt --check
forge build --sizes
forge test -vvv
```

The current public suite contains 18 Python pipeline/workflow tests and 53
Solidity tests. Solidity coverage includes unit, fuzz, regression, and a
stateful invariant campaign of 4,096 calls across 128 runs with zero reverts.

## Documentation

- [`docs/DECISION-PIPELINE.md`](docs/DECISION-PIPELINE.md): stage contracts and model boundaries
- [`docs/PAYMENT-LIFECYCLE.md`](docs/PAYMENT-LIFECYCLE.md): x402 quote, delivery, completion, and refund
- [`docs/PRIVACY.md`](docs/PRIVACY.md): retention and sensitive-data boundary
- [`docs/THREAT-MODEL.md`](docs/THREAT-MODEL.md): trust assumptions and abuse cases
- [`docs/INTEGRATION.md`](docs/INTEGRATION.md): embedding the pipeline and payment adapter
- [`docs/AGENT-DISCOVERY.md`](docs/AGENT-DISCOVERY.md): x402 OpenAPI discovery and runtime challenge requirements
- [`docs/ROADMAP.md`](docs/ROADMAP.md): planned SDK, adapter, verification, and audit work

## Security status

The public code has automated adversarial, concurrency, fuzz, and invariant
coverage. It has **not received an independent professional audit**. Model
review is probabilistic, caller declarations are not independently verified,
and the service does not authorize or execute the returned action. Read
[`SECURITY.md`](SECURITY.md) before using real funds.

## Live product and license

The active deployment powers [ResolveSignal](https://resolvesignal.com). This is
a deployment statement, not a claim of third-party adoption or user traction.

- Quote intake: `POST https://resolvesignal.com/v2/requests`
- Paid resource: `POST https://resolvesignal.com/v2/requests/{call_id}/pay`
- OpenAPI: <https://resolvesignal.com/openapi.json>
- Integration guide: <https://resolvesignal.com/integrate>
- Price and network: 0.06 USDC per call on Arc Mainnet (`eip155:5042`)

MIT. See [LICENSE](LICENSE).
