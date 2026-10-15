# Integrate ResolveSignal into a system without an LLM

No LLM is required in the calling system. ResolveSignal performs the bounded
analysis. Your application supplies current structured evidence, pays one x402
quote, receives one typed recommendation, and retains execution authority.

ResolveSignal uses x402 v2 `exact` on Arc Mainnet (`eip155:5042`). Read the live
form, prove payer control, submit the complete request, and inspect its HTTP 402
quote. The quote binds the request to one initialized escrow vault and a 0.06
USDC service fee. Pay the returned `/v2/requests/{call_id}/pay` resource once.
The service returns the checked result inline, releases the fee after delivery,
and uses the onchain refund path when a paid processing failure qualifies.

## Choose an integration surface

Optional proposal review: put `proposed_action_id` in runtime evidence to name a
declared capability with its fixed arguments. Check `/v2/form` for server support
first. The field is hidden from admission, planning and checking; trusted code
compares the validated selection and returns `decision.proposal_review` with
`retain` or `replace`. This does not authorize execution, prove optimality, or
establish that a replaced proposal was unsafe. An invalid reference is rejected
before payment. Ordinary requests omit the field or use null. A changed proposal
requires a new request/idempotency key. Fee and refund rules are unchanged.

- **Python:** use the reference package and Circle CLI payment adapter.
- **Any other language:** use the published JSON schemas and the HTTP/x402 flow.
- **Coding Agent:** give it the dedicated integration prompt. The prompt tells it
  to implement the same state machine in the repository's native language.

Download the [Python integration package](https://resolvesignal.com/integration/resolvesignal-python.zip),
[profile schema](https://resolvesignal.com/integration/profile-schema.json), and
[runtime schema](https://resolvesignal.com/integration/runtime-schema.json). The live
[`GET /v2/form`](https://resolvesignal.com/v2/form) response remains authoritative.
Start from the [example profile](https://resolvesignal.com/integration/profile.example.json) and
[example runtime evidence](https://resolvesignal.com/integration/runtime.example.json); replace every
example value with declarations and current evidence from your own system.

## Keep static policy separate from runtime evidence

Store these fields in a reviewed profile in your own repository:

- `objective`
- `policy`
- `capabilities`
- `locale`

Supply these fields for every call from current system data:

- `current_state`
- `observations`
- `facts`
- `previous_attempts`
- `observed_at`

The SDK merges both documents locally. ResolveSignal does not store a customer
profile. This keeps each purchase stateless and prevents stale runtime evidence
from being hidden inside configuration.

## Install the Python reference package

```bash
python -m pip install https://resolvesignal.com/integration/resolvesignal-python-0.1.1.zip
```

Integration Kit version **0.1.1**, MIT licensed. Source and offline tests are in
[`toolkits/python`](https://github.com/duclucky/resolvesignal-decision-pipeline/tree/main/toolkits/python).
The downloadable archive includes `LICENSE`, package metadata and `SOURCE.json`
with the source-file hashes. The machine manifest publishes the ZIP SHA-256;
compare it before installation. The public release page provides versioned
artifacts when published; do not assume an unpublished candidate is available.

From the source checkout, install the client separately from the decision core:
`python -m pip install ./toolkits/python`. From the extracted archive, use
`python -m pip install .`. The root decision-core package does not install this
client. Run offline client tests from the toolkit directory with
`python -m pip install -e ".[dev]"` and `python -m pytest tests -q`.

The package requires Python 3.12+, `httpx`, and `jsonschema`. A paid call through
the built-in adapter also requires an authenticated Circle Agent Wallet CLI on
Arc Mainnet. The package never asks for or stores a private key.

## Build and validate without payment

Run from `toolkits/python` in the source checkout or an extracted ZIP: it includes
`examples/profile.json` and `examples/runtime.json`. If you installed the ZIP
directly with pip, download the examples into the current directory first:

```bash
python -c "from pathlib import Path; from urllib.request import urlretrieve; Path('examples').mkdir(exist_ok=True); urlretrieve('https://resolvesignal.com/integration/profile.example.json', 'examples/profile.json'); urlretrieve('https://resolvesignal.com/integration/runtime.example.json', 'examples/runtime.json')"
```

The following one-line commands work in Bash and PowerShell:

```bash
resolvesignal build --profile examples/profile.json --runtime examples/runtime.json --output request.json

resolvesignal validate --profile examples/profile.json --runtime examples/runtime.json

resolvesignal check --base-url https://resolvesignal.com
```

`build` and `validate` are local. `check` only reads `/health` and `/v2/form`.
None of these commands creates a quote, calls a model, signs data, or spends USDC.

## Make one authorized paid call

The bundled English examples are synthetic, dated fixtures for offline validation,
not current observations. Before calling the live API, collect genuine evidence
from your own system, update all affected fields and use the actual observation
time. Do not make old evidence look fresh by changing only `observed_at`.
Use a unique recovery file for each authorized call; keep unresolved files intact.

```bash
resolvesignal call --profile examples/profile.json --runtime examples/runtime.json --payer 0xYOUR_AGENT_WALLET --max-fee 0.06 --recovery resolvesignal-recovery.json --confirm-paid-call
```

The explicit flag prevents setup scripts and test suites from purchasing by
accident. The SDK validates the live contract and quote, writes recovery metadata,
invokes the payment adapter exactly once, and checks that the result is bound to
the quoted call and input hash. It never automatically purchases a replacement
call after an error or timeout.

The recovery file contains the request key, call ID, input hash, payer, vault,
amount, quote expiry, and any retrieved financial status. Obtain the refund
deadline and authoritative vault state from the status/recovery endpoint; the
client does not store every contract deadline. It does not contain business input or
output. Protect this file as a credential.

## Reconcile without another payment

```bash
resolvesignal reconcile --base-url https://resolvesignal.com --recovery resolvesignal-recovery.json
```

Use reconciliation after a network interruption or ambiguous paid response. Do
not run `call` again to discover the old call's status.

## Use the Python API

```python
import json
from pathlib import Path

from resolvesignal_integration import (
    CircleCliPayment,
    ResolveSignalClient,
    build_request,
)

profile = json.loads(Path("examples/profile.json").read_text())
runtime = json.loads(Path("examples/runtime.json").read_text())
request = build_request(profile, runtime)

with ResolveSignalClient(
    "https://resolvesignal.com",
    CircleCliPayment(),
) as client:
    result = client.call(
        request,
        payer="0xYOUR_AGENT_WALLET",
        max_fee_usdc="0.06",
        recovery_path=Path("resolvesignal-recovery.json"),
        confirm_paid_call=True,
    )

action_id = result["result"]["decision"]["action_id"]
parameters = result["result"]["decision"]["parameters"]
```

Treat the returned action as a recommendation. Before execution, enforce your
own authorization and verify the returned `pre_execution` requirements. Then map
`action_id` only to an allowlisted local handler. Never execute arbitrary text.

## Implement another wallet or language adapter

The payment boundary needs three operations:

1. Sign the exact `QuoteAdmission` EIP-712 challenge for the payer.
2. Inspect the quoted `/pay` resource without settling it.
3. Execute one standard x402 v2 exact payment on Arc Mainnet with a hard fee cap.

Preserve the same invariants:

- HTTPS origin and same-origin pay resource.
- Protocol 2, backend `escrow_v3`, network `eip155:5042`.
- USDC `0x3600000000000000000000000000000000000000`, six payment decimals.
- Exact `call_id`, `input_hash`, payer, amount and initialized vault from the
  current quote.
- Durable recovery metadata written before the payment command.
- One payment invocation; no automatic retry after an ambiguous submission.
- At least 60 seconds plus network overhead for the synchronous paid response.
- No business payload or result in recovery logs.

## Integration acceptance checks

Before enabling production purchases, verify:

1. Invalid or incomplete input fails locally.
2. The read-only contract check succeeds.
3. A quote over the configured fee cap stops before payment.
4. A simulated payment adapter is invoked once under timeout and transport errors.
5. Results are accepted only when `call_id` and `input_hash` match.
6. Only allowlisted action IDs can reach business handlers.
7. Recovery state can reconcile a call without its business payload.
8. Paid end-to-end testing is performed only with separate authorization and a
   stated purchase count and maximum fee.

## Privacy boundary

The hosted service removes business data after delivery while retaining separate
financial records for reconciliation. Model providers have separate retention
policies. See [hosted privacy](https://resolvesignal.com/privacy.md). This client
does not configure provider retention or implement the public core's server runtime.
