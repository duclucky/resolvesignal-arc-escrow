# Architecture

ResolveSignal separates declarations, probabilistic model judgment, trusted
validation, payment, and delivery. A stage cannot silently repair the output of
an earlier stage.

## Boundaries

1. **Intake** owns the public request schema and explicit-absence rules.
2. **Compiler** canonicalizes the request, evaluates declared guards, and finds
   actions that are permitted, automatic, target-matched, and verifiable.
3. **Jev admission** decides whether the compiled contract is semantically
   sufficient. This stage runs before a quote is issued.
4. **Payment adapter** owns quote binding, payment verification, completion, and
   refund. The decision core does not know how wallet custody is implemented.
5. **GPT-5.4 planner** returns only a small `DecisionIR` containing declared IDs.
6. **GPT-5.4 checker** reviews four fixed relationships and cannot add sources.
7. **Trusted validator** checks all IDs and coverage, then binds accepted claims
   to SHA-256 hashes of the exact sources used during review.
8. **Renderer** revalidates those bindings and constructs the result without
   using model-authored executable prose.
9. **Reference workflow** coordinates in-memory idempotency, per-call locks,
   bounded parallel work, delivery, terminal settlement, and context cleanup
   in one process. It trusts adapter confirmation and loses its state on restart.

The hosted service has a separate runtime. This repository's core and client
can be used independently; they are not a complete production server. See
[integration options](INTEGRATION.md) and [recovery boundaries](PAYMENT-LIFECYCLE.md).

## Important invariants

- No quote is created before deterministic and Jev admission pass.
- A paid call receives one analysis attempt; retries never create a second
  automatic payment.
- Unknown IDs, missing goal coverage, target mismatch, or unsupported semantic
  checks withhold the entire draft.
- Operation completion and real-world goal resolution remain separate.
- A result is not fee-complete until delivery is acknowledged.
- Every paid failure follows refund handling and never returns a partial draft.
- Terminal receipts contain no input payload or result body.
- Each call has its own context and lock; the concurrency semaphore limits only
  aggregate model work.

## Onchain settlement

`ExactEscrowFactory` verifies an operator-signed EIP-712 quote and deploys one
deterministic minimal-proxy vault for its `callId`. The quote binds payer,
amount, terms commitment, quote expiry, and delivery deadline.

`ExactPaymentVault` has one terminal outcome:

```text
                         validated delivered result
                       ┌──────────────────────────────> Completed ──> treasury
signed quote ─> Open ──┤
                       └──────────────────────────────> Refunded ───> payer
                         paid failure or timeout
```

The contract never receives the raw request or result.
