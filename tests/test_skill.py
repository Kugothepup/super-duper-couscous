"""The community-research skill: every crp command it names exists, every example it shows passes the schemas,
and every reference file it points to is there."""
import json
import re
from pathlib import Path

import pytest
import yaml

from crp.cli import build_parser
from crp.schemas import Codebook, Hypothesis, Insight, Job, Observation, Opportunity

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude" / "skills" / "community-research"
DOCS = [SKILL / "SKILL.md"] + sorted((SKILL / "reference").glob("*.md"))
PLANNED = {"round", "paste", "status", "reset", "ui"}  # Phase 7b and 7c (D35, D36): named only as coming later
COMMAND = re.compile(r"\bcrp ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?")


def commands() -> dict[str, set[str]]:
    """Each crp command, with its actions or views where it has them."""
    sub = build_parser()._subparsers._group_actions[0]
    out = {}
    for name, p in sub.choices.items():
        nested = [a for a in p._actions if a.__class__.__name__ == "_SubParsersAction"]
        out[name] = set(nested[0].choices) if nested else set()
    return out


def frontmatter() -> dict:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---")[1])


def test_frontmatter_names_the_skill_and_lets_crp_run():
    fm = frontmatter()
    assert fm["name"] == "community-research"
    assert "Steeve" in fm["description"] and len(fm["description"]) <= 1024
    assert "Bash(python -m crp:*)" in fm["allowed-tools"]


def code_lines(doc: Path) -> list[tuple[int, str, str]]:
    """(line number, line, code in it): code blocks whole, and `inline code` elsewhere."""
    out, fenced = [], False
    for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("```"):
            fenced = not fenced
            continue
        out.append((n, line, line if fenced else " ".join(re.findall(r"`([^`]+)`", line))))
    return out


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_crp_command_named_exists(doc):
    known = commands()
    for n, line, code in code_lines(doc):
        for cmd, action in COMMAND.findall(code):
            if cmd in PLANNED:
                assert "7b" in line or "7c" in line, f"{doc.name}:{n}: crp {cmd} isn't built yet; say it's coming"
                continue
            assert cmd in known, f"{doc.name}:{n}: no command 'crp {cmd}'"
            if known[cmd] and action and not action.startswith("studies"):
                assert action in known[cmd], f"{doc.name}:{n}: 'crp {cmd}' has no '{action}'"


def test_reference_files_and_skill_point_at_each_other():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    named = set(re.findall(r"reference/([a-z-]+\.md)", text))
    present = {p.name for p in (SKILL / "reference").glob("*.md")}
    assert named == present
    for doc in DOCS:
        for path in re.findall(r"`(tests/fixtures/[^`]+)`", doc.read_text(encoding="utf-8")):
            assert (ROOT / path).exists(), f"{doc.name} names {path}, which doesn't exist"


def blocks(doc: str, lang: str) -> list[str]:
    return re.findall(rf"```{lang}\n(.*?)```", (SKILL / "reference" / doc).read_text(encoding="utf-8"), re.S)


def test_synthesis_examples_pass_the_schemas():
    models = {"post_id": Observation, "confidence": Insight, "job": Job, "kind": Opportunity}
    seen = set()
    for block in blocks("synthesis.md", "json"):
        data = json.loads(block)
        key = next(k for k in models if k in data)
        models[key].model_validate(data)
        seen.add(key)
    assert seen == set(models)


def test_hypothesis_example_passes_the_schema():
    (block,) = blocks("hypotheses.md", "json")
    for h in json.loads(block)["hypotheses"]:
        Hypothesis.model_validate(h)


def test_codebook_example_passes_the_schema():
    (block,) = blocks("codebook.md", "yaml")
    Codebook.model_validate(yaml.safe_load(block))


def test_capture_example_has_the_fields_ingest_reads():
    (block,) = blocks("capture.md", "json")
    cap = json.loads(block)
    assert {"source_file", "site", "captured", "thread_title", "search_query", "posts"} <= set(cap)
    assert set(cap["posts"][0]) == {"id", "author", "date", "date_approx", "parent", "score", "text"}


def test_the_skill_never_tells_the_ai_to_read_sealed_files():
    for doc in DOCS:
        for line in doc.read_text(encoding="utf-8").splitlines():
            if "sealed/" in line and "results/prior.md" not in line:
                assert re.search(r"(?i)never|don't|himself|only `crp unseal`", line), f"{doc.name}: {line}"
