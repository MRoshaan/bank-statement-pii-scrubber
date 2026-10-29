# AI tools used

## Coding assistant

- **Tool:** OpenCode 2.0.27
- **Model:** DeepSeek V4.1 Flash (`opencode-go/deepseek-v4.1-flash`)
- **Use:** architecture, code generation, debugging, test authoring, documentation, and packaging.
- **Subagents:** none.

## Testing tools

- **Playwright 1.64.1** with the system Chrome (`playwright-core`) for the headless end-to-end frontend check.
- **pytest 8**, **ruff**, **Docker/PostgreSQL 16**, **curl**.

## Runtime AI dependency

- **Groq API**
- **Model:** `openai/gpt-oss-120b` (fallback `openai/gpt-oss-20b`)
- **Use:** budgeting analysis and grounded chat. This is a product dependency, not a coding assistant.

## Disclosure

The provided sample statements were inspected locally during development to verify the scrubber, as requested. The task's AI policy says task data should not be pasted into AI tools. That inspection is therefore disclosed here. The submitted transcript redacts statement PII and the Groq API key. No raw statement data was sent to Groq or any external analysis API; only scrubbed text/facts are sent at runtime.

## Transcript files

- `docs/AI_TRANSCRIPT.md` — full user/assistant-visible conversation and tool calls, with PII and the API key redacted; assistant internal reasoning omitted.
- `prompts.txt` — user prompts only, in order, with the same redactions.

## Review pass

OpenAI Codex reviewed and fixed privacy boundaries, upload limits, source tracking, transaction parsing, grounding, and UI request handling. No subagents were used. Model metadata records gpt-6.1-sol; it appears in the review transcript. Tests used pytest/ruff and Playwright with local Chrome; live analysis/chat used Groq with scrubbed context.

The complete OpenCode export is in docs/AI_TRANSCRIPT_FULL.md; the earlier capped export remains in docs/AI_TRANSCRIPT.md. The Codex visible-message snapshot is in docs/AI_REVIEW_TRANSCRIPT.md; the earlier tool trace is preserved in docs/AI_REVIEW_TOOL_SNAPSHOT.md. prompts.txt combines both sets of user prompts. Re-export the Codex session after the final reply before submitting.
