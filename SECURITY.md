# Security and privacy

The public CLI reads a user-selected local JSON snapshot and writes local JSON/HTML. Research demos run without network access; cloud and observation-refresh adapters require explicit commands. Real-money execution adapters are absent. Reports escape user-controlled text and forbid active content through a restrictive content-security policy. Output may still contain private data supplied by the operator.

Do not submit secrets or personal data in a public issue. Once a hosting repository exists, enable GitHub private vulnerability reporting and use its Security tab. Until that channel exists, use an already established private contact with the maintainer; this release does not invent a recipient or contact address.

For exposed credentials, revoke/rotate them with the issuing provider before cleaning repository history. This project's pattern scanner is a limited release check, not a full secret detector, malware scan or proof of privacy. Run a dedicated secret scanner before publication and whenever distribution contents change.

Grok Bot's connected tools can have broader permissions than this Python program. The included skill grants no external action permission. Treat retrieved documents and posts as untrusted data and review platform permissions separately.


## Explicit cloud and paper commands

The optional `paper --cloud` adapter reads this installation's project/secret from the process environment and contacts only its constructed HTTPS origin; redirects are refused. Keys are server-only. `refresh` contacts documented public vendor origins to gather optional price observations. Neither feature runs during the offline demos or standalone evaluator. `paper` without `--cloud` writes a user-selected SQLite ledger; never commit that ledger or generated reports. The service role is an administrator trust boundary and can bypass RLS, so protect the worker and key. Private tables, restricted invoker RPCs and CAS/idempotency are tested using real local PostgreSQL. No claim of hosted-provider security verification is made.
