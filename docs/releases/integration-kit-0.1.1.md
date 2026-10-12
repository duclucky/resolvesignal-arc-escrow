# Integration Kit 0.1.1

Owner approved publication on 2026-10-12 after local verification. The versioned
ZIP and checksums are distributed through the
[GitHub release](https://github.com/duclucky/resolvesignal-decision-pipeline/releases/tag/v0.1.1).

The MIT Python client now has public-source layout under `toolkits/python`,
offline payment-boundary tests, explicit license metadata and `SOURCE.json`.
English synthetic examples retain their original observation time; the guide
distinguishes local validation from a live purchase and uses actual archive paths
with one-line commands for Bash and PowerShell.

The decision core's reference workflow now rejects reuse of a request key with
changed content or payer during admission, after quote creation and after
terminal cleanup. Its idempotency remains in-memory and single-process; this
release does not add a production journal or claim restart-safe payment handling.
Architecture, integration, privacy and adapter confirmation boundaries are clarified.

## Build and verify

From the repository root:

```bash
python scripts/build_integration_kit.py --output .release/integration
```

The build verifies the normalized source hashes before emitting:

- `resolvesignal-python-0.1.1.zip`
- `SHA256SUMS`

ZIP SHA-256:

```text
778eb2b9c9fb8570004129721b3418d6c1f5238bcb201f30ff946bf689385716
```

Public-source build, hosted distribution candidate and static export are byte
identical. The archive contains 11 explicitly allowed files; it has no signer,
wallet credentials or customer payloads. Source-file hashes are in `SOURCE.json`.

Local verification: 24 decision-core/workflow tests, 11 standalone client tests,
15 website/integration tests, Ruff and relative documentation-link checks passed.
The ZIP installed in an isolated Python 3.13 environment and offline CLI build
and validation passed using the installed package. CI targets Python 3.12;
remote CI results are available in the repository's Actions tab. Solidity
contracts were unchanged and their tests were not rerun locally for this change.

No paid request or shared-network transaction was made. Independent security
review and direct Agent Commitments/x402 integration remain pending. These local
checks do not establish production security or validate paid end-to-end behavior.
