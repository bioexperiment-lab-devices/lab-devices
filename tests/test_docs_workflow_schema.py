"""docs/workflow-schema.md is executable documentation.

Every complete workflow in the reference is loaded through the real loader and the real
expander, and every fragment is parsed as JSON. A reference nobody runs is a reference that
silently stops describing the code; this is the check that stops that (design 2026-07-20 §8).
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.expand import expand_dict
from lab_devices.experiment.serialize import workflow_from_dict

DOC = Path(__file__).resolve().parents[1] / "docs" / "workflow-schema.md"

# ```json  -> a COMPLETE workflow document, loaded and expanded.
# ```jsonc -> a fragment; must still be a self-contained, parseable JSON object.
_FENCE = re.compile(r"^```(json|jsonc)\n(.*?)^```", re.MULTILINE | re.DOTALL)


def _snippets(lang: str) -> list[tuple[int, str]]:
    text = DOC.read_text()
    out: list[tuple[int, str]] = []
    for match in _FENCE.finditer(text):
        if match.group(1) == lang:
            line = text.count("\n", 0, match.start()) + 1
            out.append((line, match.group(2)))
    return out


def _ids(pairs: list[tuple[int, str]]) -> list[str]:
    return [f"L{line}" for line, _ in pairs]


WORKFLOWS = _snippets("json")
FRAGMENTS = _snippets("jsonc")


def test_the_reference_actually_contains_examples() -> None:
    """Guard against a vacuous pass: an empty doc must not look like a green one."""
    assert DOC.exists(), "docs/workflow-schema.md is the repo's schema reference"
    assert len(WORKFLOWS) >= 6, f"only {len(WORKFLOWS)} complete workflows in the reference"
    assert len(FRAGMENTS) >= 4, f"only {len(FRAGMENTS)} fragments in the reference"


@pytest.mark.parametrize("line,src", WORKFLOWS, ids=_ids(WORKFLOWS))
def test_documented_workflow_loads(line: int, src: str) -> None:
    """Every ```json block is a whole document the shipped loader accepts."""
    doc: Any = json.loads(src)
    assert doc.get("schema_version") == 2, f"line {line}: reference examples are schema 2"
    workflow = workflow_from_dict(doc)
    assert workflow.schema_version == 2


@pytest.mark.parametrize("line,src", WORKFLOWS, ids=_ids(WORKFLOWS))
def test_documented_workflow_expands(line: int, src: str) -> None:
    """...and survives expansion, so documented groups/for_each are really expandable."""
    doc: Any = json.loads(src)
    workflow_from_dict(expand_dict(json.loads(json.dumps(doc))))


@pytest.mark.parametrize("line,src", FRAGMENTS, ids=_ids(FRAGMENTS))
def test_documented_fragment_is_valid_json(line: int, src: str) -> None:
    """Fragments are not whole documents, but they are still real JSON objects."""
    value: Any = json.loads(src)
    assert isinstance(value, dict), f"line {line}: write fragments as objects, not bare keys"


_V1_FRAGMENTS = [(line, src) for line, src in FRAGMENTS
                 if json.loads(src).get("schema_version") == 1]


def test_the_v1_snippet_the_schema_break_narrative_shows_is_really_rejected() -> None:
    """§7's whole story is 'a v1 document is rejected at load'. The doc SHOWS such a snippet;
    without this, the anti-rot suite would keep passing even if the loader silently started
    accepting v1 again, turning the reference into a lie. Every fragment the doc presents as
    v1 must actually raise."""
    assert _V1_FRAGMENTS, "the schema-break section must show at least one v1 document"
    for line, src in _V1_FRAGMENTS:
        # Pin the VERSION message, not merely WorkflowLoadError: a v1 snippet also uses the
        # removed params/for_each shapes, so it would raise for those reasons too even if the
        # version gate were dropped. Matching the version text is what makes this catch a
        # loader that silently started accepting v1 again.
        with pytest.raises(WorkflowLoadError, match="unsupported schema_version 1"):
            workflow_from_dict(json.loads(src))
