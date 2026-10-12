# Threat model

## Protected properties

- Missing or blank input never reaches payment.
- Jev rejection or unavailability never creates a customer charge.
- Models cannot introduce undeclared tools, parameters, goals, or sources.
- A model cannot bypass deterministic candidate filtering or policy guards.
- Semantic review covers exactly four required claims and is bound to source
  hashes owned by trusted code.
- Invalid paid output is withheld and routed to refund.
- One idempotency key binds payer and canonical input hash to one call within
  a single reference workflow instance. Changed content/payer is rejected.
- Concurrent calls retain separate contexts, results, and payment recipients.
- A terminal receipt contains no input or result body.
- Onchain completion transfers only the exact fee to treasury; refund and
  surplus return only to the payer.

## Covered cases

Tests cover blank and explicit-absence handling, invalid cross-references,
guard rejection, Jev rejection, invented action IDs, uncertain semantic claims,
concurrent orders, idempotent submissions, delivery failure, paid quality
failure, context purge, unauthorized settlement, replay, reentrancy, late
payments, surplus, blocked recipients, and multi-vault conservation.

## Trust assumptions

- Caller declarations may be false; the service validates consistency, not the
  truth of external evidence.
- Jev and GPT-5.4 are probabilistic and can share errors.
- The operator controls model/provider selection and the settlement signer.
- The caller remains responsible for current authority, target identity, and
  execution of the returned action.
- Circle/USDC issuer controls, the Arc network, RPCs, facilitators, and managed
  signer services remain external dependencies.
- The reference workflow trusts adapter receipts. Adapters must verify final
  chain outcomes; a broadcast hash or RPC timeout is not settlement evidence.
- Reference keys, locks and receipts are process-local. Durable recovery and
  coordination across workers are deployment responsibilities, not guarantees
  supplied by this implementation.

## Out of scope

- Guaranteeing a real-world business outcome.
- Executing the recommended action for the caller.
- Compromise of a model provider, signer, host, wallet, or secret manager.
- Legal, sanctions, tax, or regulatory compliance.
