from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.export_ai_transcript import SECRET_RE, redact  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _block(text: str) -> str:
    longest = max((len(match.group()) for match in re.finditer(re.escape(chr(96)) + "+", text)), default=0)
    fence = chr(96) * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def export(session_path: Path, include_tools: bool = False) -> None:
    events = [json.loads(line) for line in session_path.read_text().splitlines() if line.strip()]
    models = sorted({event["payload"]["model"] for event in events if event.get("type") == "turn_context" and event.get("payload", {}).get("model")})
    lines = [
        "# Codex review transcript", "",
        "- Tool: OpenAI Codex",
        "- Model metadata: " + (", ".join(models) or "not recorded"),
        "- Subagents: none", "",
        "Export of saved user/assistant-visible messages through this snapshot. "
        "Private reasoning, platform instructions, and binary image data are excluded. "
        "PII and credentials are redacted locally. Use --include-tools for tool calls/results; "
        "the earlier tool trace is preserved in AI_REVIEW_TOOL_SNAPSHOT.md. "
        "Run this exporter again after the final reply to include the completed conversation.", "",
    ]
    prompts = []
    for event in events:
        if event.get("type") != "response_item":
            continue
        item = event.get("payload") or {}
        kind = item.get("type")
        if kind == "message":
            role = item.get("role")
            if role not in {"user", "assistant"} or item.get("channel") == "analysis":
                continue
            text = "\n".join(str(part.get("text", "")) for part in item.get("content", []) if part.get("type") in {"input_text", "output_text", "text"})
            if not text.strip():
                continue
            safe = redact(text)
            lines.extend(["## " + role.capitalize(), "", safe, ""])
            if role == "user":
                prompts.append(safe)
        elif include_tools and kind in {"function_call", "custom_tool_call"}:
            name = item.get("name", "tool")
            text = str(item.get("arguments", item.get("input", "")))
            lines.extend(["### Tool call: " + str(name), "", _block(redact(text)), ""])
        elif include_tools and kind in {"function_call_output", "custom_tool_call_output"}:
            output = item.get("output", "")
            text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, indent=2)
            lines.extend(["### Tool result", "", _block(redact(text)), ""])
    transcript = "\n".join(lines).strip() + "\n"
    if SECRET_RE.search(transcript):
        raise RuntimeError("Credential guard rejected transcript export.")
    (ROOT / "docs/AI_REVIEW_TRANSCRIPT.md").write_text(transcript)
    review_prompts = "\n\n---\n\n".join(prompts).strip() + "\n"
    (ROOT / "docs/AI_REVIEW_PROMPTS.txt").write_text(review_prompts)
    original_path = ROOT / "docs/AI_ORIGINAL_PROMPTS.txt"
    original = original_path.read_text() if original_path.exists() else (ROOT / "prompts.txt").read_text()
    (ROOT / "prompts.txt").write_text(original.strip() + "\n\n---\n\n" + review_prompts)
    print(f"Review export: {len(prompts)} user messages; {len(transcript)} characters; models={models}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export a redacted Codex review without private reasoning.")
    parser.add_argument("session_jsonl", type=Path)
    parser.add_argument("--include-tools", action="store_true", help="Include full tool text; large traces take longer to redact.")
    args = parser.parse_args()
    export(args.session_jsonl, include_tools=args.include_tools)
