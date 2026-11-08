import json
import re
from pathlib import Path

import yaml

from tests.template.support import PYTHON_VERSION, ROOT

PLUGIN_SKILL = ROOT / "skills/fast-ddd-init/SKILL.md"


def frontmatter(path: Path) -> tuple[dict[str, object], str]:
    _, header, body = path.read_text().split("---\n", 2)
    return yaml.safe_load(header), body


def test_manifests_declare_one_plugin_from_the_repository_root() -> None:
    claude = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
    agent_plugins = json.loads((ROOT / "plugin.json").read_text())
    marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
    assert claude["name"] == agent_plugins["name"] == marketplace["name"] == "fast-ddd"
    assert agent_plugins["$schema"] == (
        "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    )
    assert [(plugin["name"], plugin["source"]) for plugin in marketplace["plugins"]] == [
        ("fast-ddd", "./")
    ]
    assert not (ROOT / ".agents/plugins").exists()
    assert sorted(path.name for path in (ROOT / "skills").iterdir()) == ["fast-ddd-init"]


def test_init_skill_is_manual_only_on_every_host() -> None:
    metadata, _ = frontmatter(PLUGIN_SKILL)
    assert metadata == {
        "name": "fast-ddd-init",
        "description": metadata["description"],
        "disable-model-invocation": True,
    }
    assert isinstance(metadata["description"], str)
    assert metadata["description"]
    codex = yaml.safe_load((PLUGIN_SKILL.parent / "agents/openai.yaml").read_text())
    assert codex == {"policy": {"allow_implicit_invocation": False}}


def sections(body: str) -> dict[str, str]:
    parts = re.split(r"(?m)^(#{1,2} .+)$", body)
    return {heading: text.strip() for heading, text in zip(parts[1::2], parts[2::2], strict=True)}


INIT_SKILL_RULES = {
    "# Create a fast-ddd service": (
        "stop at the first failure; never fall back to another version, source, or template",
    ),
    "## 1. Template source": (
        "Use the template version as `<version>`; the template tag is `v<version>`.",
        "Use the template source as `<source>`.",
        "do not read any file to look them up or replace them.",
        "Use `<source>` as the Copier source, never this plugin's installed directory.",
    ),
    "## 2. Confirm the inputs": (
        "**Destination directory**: a path that does not exist or is an empty directory.",
        "Show the service name, destination, `<source>`, and tag `v<version>`, then wait for the"
        " user's explicit confirmation before running any command.",
        "If the destination exists and is not empty, stop and ask for another destination;"
        " never write into it.",
    ),
    "## 3. Check prerequisites": (
        '`git ls-remote "<source>" "refs/tags/v<version>"` prints the tag.',
        "configure Git credentials for HTTPS (for example `gh auth setup-git`) and stop.",
        "No output: the tag is not published. Report it and stop.",
    ),
    "## 4. Create the service": (
        "ask the user to approve running the command outside the sandbox",
        "report its output and stop.",
    ),
    "## 5. Verify the answers": (
        "`_src_path` equals `<source>` and `_commit` equals `v<version>`. Report any mismatch",
    ),
    "## 6. Hand over": (
        "Open a new agent session in `<destination>`",
        "Ask the service's `fast-ddd` skill to set up secret protection for this host",
    ),
}
HAND_OVER_SECRET_PROTECTION = (
    "Ask the service's `fast-ddd` skill to set up secret protection for this host before using"
    " real configuration; its secret-protection workflow proposes user-level settings and applies"
    " them only after the user approves."
)


def test_init_skill_steps_keep_the_manual_creation_contract() -> None:
    _, body = frontmatter(PLUGIN_SKILL)
    steps = sections(body)
    assert list(steps) == list(INIT_SKILL_RULES)
    for heading, rules in INIT_SKILL_RULES.items():
        for rule in rules:
            assert rule in " ".join(steps[heading].split()), (heading, rule)


def test_init_skill_copies_the_validated_name_with_the_pinned_tools() -> None:
    _, body = frontmatter(PLUGIN_SKILL)
    copier = yaml.safe_load((ROOT / "copier.yml").read_text())
    steps = sections(body)
    (name_pattern,) = re.findall(r"regex_search\('([^']+)'\)", copier["service_name"]["validator"])
    assert f"`{name_pattern}`" in steps["## 2. Confirm the inputs"]
    (command,) = re.findall(r"```sh\n(.*?)```", steps["## 4. Create the service"], re.DOTALL)
    copier_version = copier["_min_copier_version"]
    assert command == (
        f"uvx --python {PYTHON_VERSION} --from copier=={copier_version} copier copy \\\n"
        '  --vcs-ref "v<version>" --defaults \\\n'
        '  -d service_name="<service name>" \\\n'
        '  "<source>" "<destination>"\n'
    )


def test_init_skill_carries_the_template_source_without_locating_files() -> None:
    _, body = frontmatter(PLUGIN_SKILL)
    copier = yaml.safe_load((ROOT / "copier.yml").read_text())
    declared = re.findall(r"(?m)^- (Template version|Template source): `([^`]*)`$", body)
    assert declared == [
        ("Template version", copier["kernel_version"]["default"]),
        ("Template source", copier["kernel_git_url"]["default"]),
    ]
    referenced = set(re.findall(r"[\w.<>/-]*\.(?:ya?ml|json|toml|md|lock|py|cfg|ini|txt)\b", body))
    assert referenced == {
        ".copier-answers.yml",
        "<destination>/.copier-answers.yml",
        "docs/template-operations.md",
    }
    assert "../" not in body
    assert "${CLAUDE_" not in body


def test_operations_guide_lists_user_level_installation_for_each_host() -> None:
    guide = (ROOT / "template/docs/template-operations.md").read_text()
    for command in (
        "claude plugin marketplace add benwu95/fast-ddd-service",
        "claude plugin install fast-ddd@fast-ddd",
        "codex plugin marketplace add benwu95/fast-ddd-service",
        "codex plugin add fast-ddd@fast-ddd",
        "agy plugin install https://github.com/benwu95/fast-ddd-service",
    ):
        assert command in guide


def test_init_skill_hands_secret_protection_to_the_service_skill() -> None:
    _, body = frontmatter(PLUGIN_SKILL)
    hand_over = sections(body)["## 6. Hand over"]
    items = [
        " ".join(item.split())
        for item in re.findall(r"^\d+\. (.+?)(?=^\d+\. |\Z)", hand_over, re.MULTILINE | re.DOTALL)
    ]

    assert len(items) == 3
    assert items[2] == HAND_OVER_SECRET_PROTECTION


README_SECTIONS = ("Repo 結構", "建立服務", "服務內的 fast-ddd skill", "開發與驗證", "文件")


def test_readme_links_and_make_targets_exist() -> None:
    readme = (ROOT / "README.md").read_text()
    sections = re.findall(r"^## (.+)$", readme, re.MULTILINE)
    links = re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", readme)
    commands = re.findall(r"\bmake (?:-C (\S+) )?([a-z][a-z-]*)", readme)

    assert set(README_SECTIONS) <= set(sections)
    structure = readme.split("## Repo 結構", 1)[1].split("\n## ", 1)[0]
    for path in ("kernel/", "template/", "example/", ".claude-plugin/", "docs/"):
        assert f"`{path}`" in structure
    local = [link for link in links if "://" not in link]
    assert local
    assert [link for link in local if not (ROOT / link).exists()] == []
    assert commands
    missing = [
        (directory or ".", target)
        for directory, target in commands
        if not re.search(
            rf"^{re.escape(target)}:", (ROOT / directory / "Makefile").read_text(), re.MULTILINE
        )
    ]
    assert missing == []
