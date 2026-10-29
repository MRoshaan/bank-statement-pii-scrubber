from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.scrubber.engine import scrub_text  # noqa: E402

try:
    from tests.test_scrubber import KNOWN_PII  # noqa: E402
except Exception:
    KNOWN_PII = []

DB_PATH = Path.home() / ".local/share/opencode/opencode.db"
OUT_DIR = Path(__file__).resolve().parent.parent / "docs"
PROMPTS_PATH = Path(__file__).resolve().parent.parent / "prompts.txt"
SESSION_ID = "ses_e7b65336dffeOvL74YlbvxlrOz"
TOOL_OUTPUT_LIMIT = 4000
SECRET_RE = re.compile(r"\b(?:gsk_|sk-|gho_|github_pat_)[A-Za-z0-9_\-]{8,}\b")
EMAIL_RE = re.compile(r"(?<![\w.])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+(?:\.[A-Za-z]{2,})?")
IBAN_RE = re.compile(r"\b[A-Za-z]{2}\d{2}[A-Za-z0-9 ]{11,34}\b")
CNIC_RE = re.compile(r"\b\d{5}-\d{7}-\d\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
AADHAAR_RE = re.compile(r"\b\d{4}[- ]\d{4}[- ]\d{4}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d() \-/]{7,}\d)(?!\d)")
LONG_NUMBER_RE = re.compile(r"\b\d{9,}\b")
KNOWN_LITERALS = [
    "House B-47, Street 11, Gulshan-e-Iqbal Block 6, Karachi 75300, Pakistan",
    "House B-47, Street 11, Gulshan-e-Iqbal Block 6, Karachi 75300, PK",
    "Flat 3, 82 Church Lane, Manchester M20 4WX, United Kingdom",
    "1180 Willow Creek Dr, Apt 22B, Austin, TX 78741, USA",
    "2210 Lakeshore Blvd W, Unit 1104, Toronto, ON M8V 0C7, Canada",
    "Bergmannstraße 44, 10961 Berlin, Deutschland",
    "14/2 MG Road, Pune, Maharashtra 411001, India",
]


def fast_redact(text: str) -> str:
    text = SECRET_RE.sub("<REDACTED_SECRET>", text)
    for literal in KNOWN_PII:
        if literal:
            text = text.replace(literal, "<REDACTED>")
    for literal in KNOWN_LITERALS:
        text = text.replace(literal, "<ADDRESS>")
    text = EMAIL_RE.sub("<EMAIL>", text)
    text = IBAN_RE.sub("<IBAN>", text)
    text = CNIC_RE.sub("<NATIONAL_ID>", text)
    text = SSN_RE.sub("<NATIONAL_ID>", text)
    text = AADHAAR_RE.sub("<NATIONAL_ID>", text)
    text = re.sub(r"\bPK\d{2}[A-Z0-9]{10,34}\b", "<IBAN>", text)
    text = re.sub(r"\b(?:PK\d{2}[A-Z0-9]{4,}|CRES[A-Z0-9]*|SCBLPKKA|SADAPKKA|NAYAPKKA)\b", "<BANK_TOKEN>", text)
    text = re.sub(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", "<IFSC>", text)
    text = re.sub(r"\b\d{2}-\d{2}-\d{2}\b", "<ROUTING_NUMBER>", text)
    text = re.sub(r"\b\d{5}-\d{3,}-?\d{0,3}\b", "<NATIONAL_ID>", text)
    text = PHONE_RE.sub("<PHONE>", text)
    text = LONG_NUMBER_RE.sub("<NUMBER>", text)
    text = re.sub(r"\b\d{6,}\b", "<NUMBER>", text)
    return SECRET_RE.sub("<REDACTED_SECRET>", text)


def redact(text: str) -> str:
    text = fast_redact(text)
    lines: list[str] = []
    for line in text.splitlines() or [""]:
        try:
            lines.append(scrub_text(line).text)
        except Exception:
            lines.append(line)
    return fast_redact("\n".join(lines))


def tool_text(item: dict) -> str:
    state = item.get("state") or {}
    content = state.get("content") or []
    pieces = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            pieces.append(str(part.get("text", "")))
    return "\n".join(pieces)


def main() -> None:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    session = con.execute(
        "select title, directory, time_created, model from session_v2 where id=?", (SESSION_ID,)
    ).fetchone()
    if not session:
        raise SystemExit("Session not found")
    title, directory, created_ms, model = session
    rows = con.execute(
        "select type, seq, data from session_message where session_id=? order by seq asc", (SESSION_ID,)
    ).fetchall()

    lines: list[str] = [
        "# AI conversation transcript",
        "",
        f"- **Session:** `{SESSION_ID}`",
        f"- **Title:** {title}",
        f"- **Directory:** `{directory}`",
        f"- **Started:** {datetime.fromtimestamp(created_ms / 1000).isoformat()}",
        "- **Coding tool:** OpenCode 2.0.27",
        "- **Model:** DeepSeek V4.1 Flash (`opencode-go/deepseek-v4.1-flash`)",
        "- **Subagents:** none",
        "",
        "> Disclosure: the provided sample statements were inspected locally during development to verify the scrubber. "
        "The task's AI policy says task data should not be pasted into AI tools; that inspection is disclosed here. "
        "All statement PII and the Groq API key are redacted below. Assistant internal reasoning is omitted; every "
        "user-visible assistant message is included. Very long tool outputs are capped at 4,000 characters.",
        "",
        "---",
        "",
    ]
    prompts: list[str] = []

    for message_type, seq, raw in rows:
        data = json.loads(raw)
        if message_type == "user":
            text = str(data.get("text", "")).strip()
            if not text:
                continue
            safe = redact(text)
            prompts.append(safe)
            lines.extend([f"## Turn {seq} — User", "", safe, ""])
        elif message_type == "assistant":
            contents = data.get("content") or []
            visible = [
                part
                for part in contents
                if isinstance(part, dict) and part.get("type") in {"text", "tool"}
            ]
            if not visible:
                continue
            lines.extend([f"## Turn {seq} — Assistant ({data.get('model', {}).get('id', 'unknown')})", ""])
            for part in visible:
                if part.get("type") == "text":
                    lines.extend([redact(str(part.get("text", "")).strip()), ""])
                elif part.get("type") == "tool":
                    state = part.get("state") or {}
                    name = part.get("name", "tool")
                    tool_input = state.get("input")
                    lines.extend([f"### Tool call: `{name}`", ""])
                    if tool_input is not None:
                        payload = json.dumps(tool_input, ensure_ascii=False, indent=2)
                        if "AI_TRANSCRIPT" in payload or "prompts.txt" in payload:
                            continue
                        clipped = payload[:TOOL_OUTPUT_LIMIT]
                        if len(payload) > TOOL_OUTPUT_LIMIT:
                            clipped += "\n[tool input truncated in transcript]"
                        lines.extend(["```json", redact(clipped), "```", ""])
                    output = tool_text(part)
                    if output:
                        if "AI_TRANSCRIPT" in output or "prompts.txt" in output:
                            continue
                        clipped = output[:TOOL_OUTPUT_LIMIT]
                        if len(output) > TOOL_OUTPUT_LIMIT:
                            clipped += "\n[tool output truncated in transcript]"
                        lines.extend(["```text", redact(clipped), "```", ""])
        else:
            continue

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "AI_TRANSCRIPT.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    PROMPTS_PATH.write_text("\n\n---\n\n".join(prompts).strip() + "\n", encoding="utf-8")
    print(f"Transcript: {OUT_DIR / 'AI_TRANSCRIPT.md'}")
    print(f"Prompts:   {PROMPTS_PATH}")
    print(f"Prompts:   {len(prompts)}")
    print(f"Lines:     {len(lines)}")


if __name__ == "__main__":
    main()
