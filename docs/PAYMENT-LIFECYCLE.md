# Payment lifecycle

The public workflow uses a `PaymentAdapter`; the Arc implementation uses one
deterministic vault per call and standard x402 v2 `exact` payment.

## Seller sequence

1. Validate and normalize the complete request.
2. Compile candidates and run Jev admission at the operator's cost.
3. Bind `callId`, payer, amount, input/terms commitment, quote expiry, and
   delivery deadline in the operator-signed quote.
4. Create or predict the vault and advertise it as x402 `payTo`.
5. Verify chain, token, payer, recipient, amount, transaction success, and call
   binding. A vault balance alone is not payer proof.
6. Run one GPT-5.4 planning and checking sequence.
7. Send the checked response body.
8. On confirmed delivery, commit the result hash and complete the exact fee.
9. On paid processing, quality, timeout, or delivery failure, refund the payer.
10. Purge the input and result context after a terminal receipt is recorded.

## Idempotency

Within one `ResolveSignalWorkflow` instance, a request key binds one payer and
the SHA-256 of canonical submitted JSON. Object-key order does not change the
binding. Changed content or payer fails, including during admission and after
terminal cleanup. Identical concurrent submissions share the in-flight quote;
a terminal key is not reopened. Only the hash survives business-context cleanup.

This reference uses RAM, not persistent storage. A new instance or process has
no knowledge of previous keys, receipts or financial attempts. It must not be
used as a production guarantee against duplicate payment after restart.

## Production adapter and recovery boundary

`verify`, `complete` and `refund` must return only after authoritative confirmation
of the bound outcome. A transaction hash, HTTP response or cached balance alone
is insufficient. The reference trusts the adapter's returned dictionary; it
does not validate chain receipts itself. A confirmation timeout is an unknown
outcome, not a failed payment or completed refund.

A production runtime must durably store request-key/payer/input-hash bindings
and financial intent **before** broadcast, coordinate workers, and reconcile
the same call and transaction after restart. Repeated adapter operations must
reuse stable financial identities. Do not reopen a key, charge again or refund
an already completed vault because an RPC response was lost. Reconcile the
onchain vault state and transaction before another financial action.

The hosted HTTP service is a separate implementation. These requirements and
the reference tests do not prove its crash recovery or independent security review.

## Recovery

- Before `completeBy`, the operator can refund.
- At or after `completeBy`, anyone can call `refund`; funds still return only to
  the bound payer.
- Late or excess USDC can only be returned to the bound payer.
- An unknown settlement is reconciled by transaction identity before any new
  financial action.

The factory and implementation contracts are not payment recipients.
