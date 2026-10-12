# Privacy and retention

## Reference workflow

`ResolveSignalWorkflow` keeps active normalized input, compiled declarations and
results in process memory. After completion or confirmed refund it removes its
request and result references. It retains request-key bindings (payer, input
hash and call ID) and financial terminal receipts in memory until the instance
is discarded. It has no durable retention store or secure memory-erasure guarantee.
Objects returned to callers, including `Delivery.result`, remain the caller's
responsibility; removing workflow references does not delete those copies.

Unknown settlement leaves context pending in this reference. Production
operators need their own bounded retention and recovery policy. This reference
behavior is separate from the hosted service's retention policy.

## Hosted ResolveSignal service

The hosted service describes deletion of business input and output after response
delivery, while retaining financial metadata for settlement and reconciliation.
Delivery and financial completion are different events: unavailable RPC can
leave recovery pending after business data has been removed. An undelivered
result has a limited recovery window. Consult the current
[hosted privacy policy](https://resolvesignal.com/privacy.md) and
[refund recovery guide](https://resolvesignal.com/refund-recovery.md) before use.

Model providers receive content required for admission, planning and checking.
Removing local data does not erase provider-side records. Their retention and
account configuration must be reviewed separately; this repository does not
establish zero retention at those providers. Do not submit secrets or data you
are not authorized to share.

## Logs and public records

Log stage codes, latency, transaction identifiers and safe schema paths, not
business payloads, prompts, outputs, wallet credentials, raw payment signatures
or API keys. Integration Kit recovery files exclude business input/output but
contain access-sensitive request keys and financial metadata; protect them.

Only addresses, value, deadlines and opaque commitments belong onchain. Public
chain records cannot be erased. Never put raw business input or output in a
quote or transaction. Hash commitments are not encryption and can reveal
low-entropy content through guessing.
