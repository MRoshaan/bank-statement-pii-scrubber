# Project review — 29 October 2026

Fixed privacy gaps at the LLM boundary, including analysis output, refusal/error metadata, conversation history, and repair prompts. Unsupported analyses now fall back to deterministic facts. A transfer reference that resembled a timestamp is removed from the outputs and existing demo data.

Upload limits now apply after ZIP expansion. Duplicate filenames keep separate transaction sources. Parsing preserves negative balances and wallet transaction times, separates adjacent amount columns, and keeps currencies separate when flagging duplicates. Chat receives complete totals for the requested category. The frontend ignores stale replies, blocks overlapping chat submissions, and fits narrow screens.

Verification:

- 59 pytest cases pass; ruff, JavaScript syntax, and Git whitespace checks pass.
- CLI scrubbing with PostgreSQL storage handles four files and 119 transactions.
- Combined/per-file outputs pass residual scans and known-PII checks.
- Browser upload, output tabs, real Groq analysis and merchant chat, currency formatting, and chat request handling pass. Food chat also passed a live service check.
- Analysis used 6,253 input tokens; food chat used 4,894. Both retained the 1,200-token output allowance.
- Responsive checks pass at 320, 390, 760, and 1440 pixels. Screenshots were inspected.
- The demo database retains one batch, four files, 119 transactions, one analysis, and no chat sessions.
- The ZIP excludes credentials, raw data, local databases, environments, caches, Git metadata, and video. Transcript and prompt exports pass credential/known-PII checks.

The video is still pending. Record it, add its link to the README, and re-export the Codex conversation after the final reply before submission. Review changes are grouped into backend, frontend, and submission commits. OCR, label-dependent addresses, and semantic limits of numeric membership validation remain documented in NOTES.md.
