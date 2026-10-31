# Optional weekly portfolio report

Configure the owning Bot, store, source universe, timezone and private report destination after a manual preview. Run after the prior week's final session is fully valued. Research/report creation needs no email permission.

```text
Read docs/CLOUD.md. Generate the IRIN portfolio report for the last completed Monday-Sunday week using this installation's ledger. Inspect report.json, report.html, report.txt and send_manifest.json. Report missing/partial weekly returns as unavailable, never zero. Keep simulated results, fees, slippage, source limitations, stale inputs and halts explicit. Show the preview in this chat unless I separately enabled this routine's report delivery to a specific recipient.

If delivery was explicitly enabled in this routine and in the ledger, QA passes, the period is complete, and send_allowed is true, atomically reserve the period with the exact HTML SHA-256. Only after that command succeeds, send the reviewed report once to the recipient configured privately in this routine. Record the provider message ID with ack-send. Any ambiguous outcome stays reserved and requires reconciliation against the provider's sent state; never automatically resend, release a hold or erase a reservation. Respect dispatch-hold. Do not send any other message or report.
```

No routine is created by this file. No dispatch permission is inherited from a previous user, installation, template or report manifest.
