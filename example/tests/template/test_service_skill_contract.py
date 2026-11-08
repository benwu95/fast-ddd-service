import importlib
import inspect
import re
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from copier import run_copy

from scripts.check_versions import MARKDOWN_FIELD
from tests.template.support import ROOT

SKILL_DIR = ROOT / "template/.agents/skills/fast-ddd"
SERVICE_SKILL = SKILL_DIR / "SKILL.md.jinja"
CODE_WORKFLOWS = (
    "bounded-context",
    "aggregate",
    "domain-command",
    "batch-operation",
    "event-handler",
    "mq-consumer",
    "background-task-and-cron",
)
WORKFLOWS = (*CODE_WORKFLOWS, "secret-protection")
RECIPES = (
    "export",
    "batch-operations",
    "archive-snapshot",
    "operation-history",
    "batch-event-handler",
    "realtime-push",
    "app-lib",
)
RECIPE_SECTIONS = ("When to use", "Files to change", "Steps", "Required tests")
RECIPE_KERNEL_APIS = {
    "batch-event-handler": ("subscribe_batch", "apply_event_batch"),
    "realtime-push": (
        "create_realtime_emitter",
        "configure_realtime",
        "push_after_commit",
        "mount_realtime",
    ),
}
KERNEL_NAME = re.compile(r"\bfast_ddd(?:_adapter|_port|_devtools)?(?:\.\w+)+")
CALL_NAME = re.compile(r"\b(\w+)\(")
CODE_WORKFLOW_SECTIONS = ("Files to change", "Rules to load", "Reference code", "Required tests")
RULE_SECTIONS = {
    "layering": ("Layers", "Dependency rules", "Shared code"),
    "time-and-serialization": ("Time", "Serialization"),
    "api": ("Routing", "Status codes", "Error codes", "Naming"),
    "security": ("Tenant isolation", "Authentication and authorization"),
    "testing": ("Required tests per aggregate", "Test infrastructure"),
}
DECISIONS = (
    "Where shared code lives",
    "Why domain events store tracing context",
    "When to enable archive snapshots",
    "When to use an event handler instead of calling a use case",
    "Nested SessionProvider use",
    "Writing a batch use case",
    "Domain command or PATCH",
    "409 or 422",
    "When a repository may use the global tenant scope",
    "Why organization_id comes from the aggregate",
)
SECRET_PROTECTION_STEPS = (
    "Identify the host.",
    "Read the current documentation.",
    "Propose user-level settings.",
    "Wait for approval.",
    "Apply.",
    "Verify with probes.",
    "Run make check.",
    "Report gaps.",
)
REFERENCE_PATH = re.compile(r"`(references/[^`\s]+)`")
ENVIRONMENT_NAMES = "python3 -c 'import os; print(sorted(os.environ))'"
NEVER_MODIFY_REPOSITORY = (
    "Never create, modify or delete tracked files or configuration in this repository,"
    " including `.env` files, project-level host settings, `.gitignore` or the"
    " template-tracked skill; the only expected writes are the ignored build and test"
    " artifacts that `make check` itself produces (`.venv/`, `.coverage`, `.pytest_cache/`,"
    " `.ruff_cache/`, `__pycache__/`)."
)


def frontmatter(path: Path) -> tuple[dict[str, object], str]:
    _, header, body = path.read_text().split("---\n", 2)
    return yaml.safe_load(header), body


def headings(text: str) -> list[str]:
    return re.findall(r"^## (.+)$", text, re.MULTILINE)


def section(text: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert match, heading
    body = match.group(1).strip()
    assert body, heading
    return body


def markdown_files() -> list[Path]:
    references = SKILL_DIR / "references"
    return [
        SERVICE_SKILL,
        *sorted(
            path
            for path in references.rglob("*.md")
            if path.relative_to(references).parts[0] != "example"
        ),
    ]


def test_service_skill_uses_portable_frontmatter_and_renders_the_kernel_version() -> None:
    metadata, body = frontmatter(SERVICE_SKILL)
    assert metadata == {"name": "fast-ddd", "description": metadata["description"]}
    assert isinstance(metadata["description"], str)
    assert metadata["description"]
    assert "{{ kernel_version }}" in body
    assert body.count("\n# fast-ddd\n") == 1
    assert "../" not in body.replace("'../uv.lock'", "")
    assert "${CLAUDE_" not in body


@pytest.mark.parametrize(("source", "lock"), [("git", "uv.lock"), ("workspace", "../uv.lock")])
def test_rendered_skill_names_the_kernel_lock_for_each_source(
    template_repository: Path, tmp_path: Path, source: str, lock: str
) -> None:
    run_copy(
        str(template_repository),
        tmp_path,
        defaults=True,
        vcs_ref="HEAD",
        quiet=True,
        data={"kernel_source": source},
    )
    skill = (tmp_path / ".agents/skills/fast-ddd/SKILL.md").read_text()

    assert dict(MARKDOWN_FIELD.findall(skill)) == {"Kernel version": "0.1.0", "Kernel lock": lock}


def test_first_step_stops_on_a_version_mismatch_without_changes() -> None:
    _, body = frontmatter(SERVICE_SKILL)
    assert headings(body)[0] == "Step 1: Check the kernel version"
    step = section(body, "Step 1: Check the kernel version")
    script = (SKILL_DIR / "scripts/check_kernel_version.py").read_text()
    failure = re.search(r'^FAILURE = "([^"]+)"$', script, re.MULTILINE)
    assert failure
    outcomes = re.findall(r"^- (.+?):", step, re.MULTILINE)
    assert outcomes == [
        "The command succeeds",
        f"The output contains `{failure.group(1)}`",
        "It fails without that message",
    ]
    assert "`make kernel-version`" in step
    assert "exit 1" not in step.lower()
    guide = (ROOT / "template/docs/template-operations.md").read_text()
    upgrade = re.search(r'"([^"]+)" in `docs/template-operations.md`', step)
    assert upgrade
    assert f"## {upgrade.group(1)}" in guide


def test_skill_lists_every_workflow_and_rule_file() -> None:
    _, body = frontmatter(SERVICE_SKILL)
    workflows = REFERENCE_PATH.findall(section(body, "Workflows"))
    rules = REFERENCE_PATH.findall(section(body, "Rules"))

    assert workflows == [f"references/workflows/{name}.md" for name in WORKFLOWS]
    assert sorted(
        path.stem for path in (SKILL_DIR / "references/workflows").glob("*.md")
    ) == sorted(WORKFLOWS)
    assert sorted(rules) == sorted(f"references/rules/{name}.md" for name in RULE_SECTIONS)
    assert sorted(path.stem for path in (SKILL_DIR / "references/rules").glob("*.md")) == sorted(
        RULE_SECTIONS
    )
    assert "`references/decisions.md`" in body


@pytest.mark.parametrize("name", CODE_WORKFLOWS)
def test_code_workflow_names_files_rules_reference_code_and_tests(name: str) -> None:
    text = (SKILL_DIR / f"references/workflows/{name}.md").read_text()
    found = headings(text)
    for heading in CODE_WORKFLOW_SECTIONS:
        assert found.count(heading) == 1, (name, heading)
    rules = REFERENCE_PATH.findall(section(text, "Rules to load"))
    assert rules
    assert {path.removeprefix("references/rules/") for path in rules} <= {
        f"{rule}.md" for rule in RULE_SECTIONS
    }
    examples = REFERENCE_PATH.findall(section(text, "Reference code"))
    assert examples
    assert all(path.startswith("references/example/") for path in examples)
    assert section(text, "Required tests")


def test_aggregate_workflow_generates_only_default_crud() -> None:
    text = (SKILL_DIR / "references/workflows/aggregate.md").read_text()
    defaults = re.findall(r"^- `([^`]+)`", section(text, "Generated by default"), re.MULTILINE)

    assert defaults == ["list", "get", "create", "PATCH", "delete"]


def test_every_referenced_skill_path_exists() -> None:
    missing = [
        (path.relative_to(SKILL_DIR).as_posix(), reference)
        for path in markdown_files()
        for reference in REFERENCE_PATH.findall(path.read_text())
        if not (SKILL_DIR / reference.rstrip("/")).exists()
    ]

    assert missing == []


@pytest.mark.parametrize("rule", RULE_SECTIONS)
def test_rule_files_cover_their_design_topics(rule: str) -> None:
    text = (SKILL_DIR / f"references/rules/{rule}.md").read_text()
    for heading in RULE_SECTIONS[rule]:
        assert headings(text).count(heading) == 1, (rule, heading)
        assert section(text, heading)


def test_decision_records_cover_each_design_decision() -> None:
    text = (SKILL_DIR / "references/decisions.md").read_text()

    assert headings(text) == list(DECISIONS)
    for heading in DECISIONS:
        assert section(text, heading)


def test_secret_protection_requires_approval_and_stays_user_level() -> None:
    text = (SKILL_DIR / "references/workflows/secret-protection.md").read_text()
    steps = re.findall(r"^\d+\. \*\*([^*]+)\*\*", section(text, "Steps"), re.MULTILINE)
    never = section(text, "Never")

    assert steps == list(SECRET_PROTECTION_STEPS)
    assert "managed settings" in never
    assert NEVER_MODIFY_REPOSITORY in re.findall(r"^- (.+)$", never, re.MULTILINE)
    probes = section(text, "Steps").split("6. **Verify with probes.**", 1)[1].split("\n7. ", 1)[0]
    commands = re.findall(r"`([^`]+)`", probes)
    assert ENVIRONMENT_NAMES in commands
    assert "wc -c < .env" in commands
    assert not [command for command in commands if command.split()[:1] in (["env"], ["printenv"])]
    assert "Required tests" not in headings(text)


def test_operations_guide_copy_examples_do_not_override_the_kernel_version() -> None:
    guide = (ROOT / "template/docs/template-operations.md").read_text()
    create = section(guide, "建立服務與環境")

    assert re.findall(r"```(?:sh|bash)?\n(.*?)```", create, re.DOTALL)
    assert "kernel_version=" not in create


def test_cited_test_names_exist_in_the_reference_copy() -> None:
    defined = {
        name
        for path in (SKILL_DIR / "references/example/tests").rglob("*.py")
        for name in re.findall(r"^(?:async )?def (test_\w+)", path.read_text(), re.MULTILINE)
    }
    cited = {
        (path.relative_to(SKILL_DIR).as_posix(), name)
        for path in markdown_files()
        for name in re.findall(r"`(test_\w+)`", path.read_text())
    }

    assert cited
    assert sorted((path, name) for path, name in cited if name not in defined) == []


def resolve_kernel_name(qualified: str) -> object:
    parts = qualified.split(".")
    for split in range(len(parts), 0, -1):
        try:
            target: object = importlib.import_module(".".join(parts[:split]))
        except ModuleNotFoundError:
            continue
        for attribute in parts[split:]:
            target = getattr(target, attribute)
        return target
    raise AssertionError(qualified)


def kernel_callables(text: str) -> dict[str, list[object]]:
    """Every callable a recipe can reach from the kernel names it mentions, by short name."""
    table: dict[str, list[object]] = {}

    def add(name: str, value: object) -> None:
        if callable(value) and not name.startswith("_"):
            table.setdefault(name, []).append(value)
        if inspect.isclass(value):
            for member, attribute in vars(value).items():
                if not member.startswith("_") and callable(attribute):
                    table.setdefault(member, []).append(attribute)

    for qualified in KERNEL_NAME.findall(text):
        target = resolve_kernel_name(qualified)
        if isinstance(target, ModuleType):
            for name, value in vars(target).items():
                if getattr(value, "__module__", "").startswith("fast_ddd"):
                    add(name, value)
        else:
            add(qualified.rsplit(".", 1)[1], target)
    return table


def top_level_keywords(text: str, start: int) -> set[str]:
    """Keyword names inside the parentheses that open at ``start``, outside nested brackets."""
    depth, index, keywords = 0, start, set[str]()
    while index < len(text):
        char = text[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return keywords
        elif depth == 1 and not (text[index - 1].isalnum() or text[index - 1] in "_."):
            match = re.match(r"(\w+)=(?!=)", text[index:])
            if match:
                keywords.add(match.group(1))
                index += len(match.group(0))
                continue
        index += 1
    return keywords


def kernel_calls(text: str) -> Iterator[tuple[str, set[str], list[object]]]:
    table = kernel_callables(text)
    for match in CALL_NAME.finditer(text):
        name = match.group(1)
        if name in table:
            yield name, top_level_keywords(text, match.end() - 1), table[name]


def accepts(function: object, keywords: set[str]) -> bool:
    if not callable(function):
        return False
    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return True
    return keywords <= set(parameters)


def recipe(name: str) -> str:
    return (SKILL_DIR / f"references/recipes/{name}.md").read_text()


def test_skill_lists_every_recipe() -> None:
    _, body = frontmatter(SERVICE_SKILL)
    recipes = REFERENCE_PATH.findall(section(body, "Recipes"))

    assert recipes == [f"references/recipes/{name}.md" for name in RECIPES]
    assert sorted(path.stem for path in (SKILL_DIR / "references/recipes").glob("*.md")) == sorted(
        RECIPES
    )


@pytest.mark.parametrize("name", RECIPES)
def test_recipe_names_when_files_steps_and_tests(name: str) -> None:
    text = recipe(name)
    found = headings(text)

    for heading in RECIPE_SECTIONS:
        assert found.count(heading) == 1, (name, heading)
        assert section(text, heading)
    assert REFERENCE_PATH.findall(text)


@pytest.mark.parametrize("name", RECIPES)
def test_recipe_kernel_names_and_keywords_exist(name: str) -> None:
    text = recipe(name)
    checked = {call for call, _, _ in kernel_calls(text)}
    unknown = [
        (call, sorted(keywords))
        for call, keywords, candidates in kernel_calls(text)
        if not any(accepts(candidate, keywords) for candidate in candidates)
    ]

    assert unknown == []
    assert set(RECIPE_KERNEL_APIS.get(name, ())) <= checked


def test_recipe_kernel_check_rejects_unknown_keywords() -> None:
    text = "Call `push_after_commit(name, 1, data, rooms=[x])` from `fast_ddd_adapter.realtime`."

    assert [
        (call, keywords)
        for call, keywords, candidates in kernel_calls(text)
        if not any(accepts(candidate, keywords) for candidate in candidates)
    ] == [("push_after_commit", {"rooms"})]


def test_export_recipe_bounds_rows_and_writes_text_cells() -> None:
    text = recipe("export")

    assert "MAX_EXPORT_ROWS = 10_000" in text
    assert re.search(r"422[^\n]*export_too_large|export_too_large[^\n]*422", text)
    assert set(re.findall(r"\blimit=(\w+)", text)) == {"MAX_EXPORT_ROWS", "1"}
    steps = section(text, "Steps")
    assert 'data_type = "s"' in steps
    assert "ILLEGAL_CHARACTERS_RE" in steps
    required = section(text, "Required tests")
    assert "tests/test_error_catalog.py" in required
    assert "\\x0b" in required


def test_batch_operations_recipe_covers_each_form() -> None:
    text = recipe("batch-operations")
    steps = section(text, "Steps")

    for form in ("Batch-create", "Batch-update", "Batch-delete"):
        assert f"{form}, use case" in steps
    for name in ("create_batch", "apply_batch", "success_status=201", "success_status=204"):
        assert name in steps
