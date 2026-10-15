# Review a proposed action in one paid call

ResolveSignal can compare a caller's proposed action with a separately generated,
validated next action. Send the usual complete V2 request with this optional field:

```json
{"proposed_action_id": "check_status"}
```

This is a field to add to a complete request, not a standalone request body.
The ID must reference a declared capability. Its exact arguments are those in
that capability; declare separate capability IDs for different parameter sets.
Omit the field or use null for ordinary next-action selection. Existing requests
and their canonical request commitments are unchanged when the field is absent.

The field is excluded from all admission, planner and checker inputs. Models
still see the ordinary capabilities, evidence and constraints. A preference
written elsewhere in caller text cannot be automatically concealed. No extra
model invocation or follow-up conversation is added. Once the independently
selected decision passes deterministic and semantic checks, trusted rendering
compares the two IDs and adds `decision.proposal_review`:

```json
{
  "status": "replace",
  "proposed_action_id": "retry_order",
  "selected_action_id": "check_status",
  "proposed_action_admissible": false,
  "basis": "independent_validated_selection",
  "execution_authorized": false,
  "limitations": "Agreement with a separately selected conditional action, not proof of optimality or real-world success. A replacement does not by itself establish that the proposal was unsafe."
}
```

`retain` means both IDs match. `replace` means they differ. Neither status grants
execution authority or certifies optimality. Structural admissibility alone does
not establish semantic suitability. Reasons, evidence references, selected fixed
parameters and pre-execution requirements remain in the existing decision fields.
The supplied proposal does not force selection or payment for an invalid result.

An unknown proposal ID is rejected before quoting. A declared but inadmissible
proposal can be replaced by an admissible action. If no admissible action exists,
the request is rejected before payment. Semantic admission rejection also precedes
payment. A failure after payment withholds the result and follows the existing
full service-fee refund workflow; a pending refund is not a confirmed refund.

Use the same x402 exact flow and configured fee (production: 0.06 USDC on Arc
Mainnet). The proposal is included in the request commitment, payer admission
proof and idempotency binding. Changing it requires a new request and idempotency
key. It is business context held in memory and purged with the result, with no
new durable business-data storage.

The Python SDK accepts `proposed_action_id` as an optional runtime field in
`build_request(profile, runtime)`. Fetch `/v2/form` before integration; a deployed
server must advertise the field in its schema before clients send it. This source
change alone does not deploy the feature.

## Verification

Run `python -m pytest python_tests -q` for the reusable core and
`python -m pytest toolkits/python/tests -q` for the standalone client.
Tests use synthetic data and fake providers and payments. They do not establish
live model quality or independent customer traction.
