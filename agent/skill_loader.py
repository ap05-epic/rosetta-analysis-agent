"""Compose the system prompt: AGENT.md + skills, in a fixed order.

Deterministic on purpose — same files, same prompt, same behavior. New skills
must be added to SKILL_ORDER explicitly; nothing is auto-discovered.
"""

from pathlib import Path

_HERE = Path(__file__).parent

SKILL_ORDER = [
    "triage.md",
    "root_cause_analysis.md",
    "fix_recommendation.md",
    "output_format.md",
]


def build_system_prompt() -> str:
    parts = [(_HERE / "AGENT.md").read_text(encoding="utf-8")]
    for name in SKILL_ORDER:
        parts.append((_HERE / "skills" / name).read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(p.strip() for p in parts)
