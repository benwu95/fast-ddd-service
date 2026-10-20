# Set up secret protection for this agent host

## When to use

- Once per machine and per agent host, typically right after the service is created, or when the user switches to another host or upgrades it.
- When the user asks to stop the agent from reading `.env` files, keys or credentials.
- This configures the agent host, not the service. It has no automated tests: host setting formats change too fast to pin, so every step follows the host's current official documentation.

## Background

- The primary defense is keeping secrets out of the agent's environment: no production or shared secrets on the local machine, and no secrets exported in the shell that starts the agent. That remains the developer's responsibility; host settings only narrow what slips through.
- Settings and secrets come from environment variables. `KernelSettings` never loads `.env`, and the template's `.gitignore` excludes `.env*`, key and certificate files. The template ships no host permission settings.
- Mechanisms seen on 2026-10-18. Treat them as hints only and re-check each against the current documentation before proposing anything:
  - Claude Code: `permissions.deny` `Read(...)` rules, the sandbox (`filesystem.denyRead`, `credentials`) and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`. Deny rules are tool-level and do not cover subprocesses such as `grep -r` or Python; `denyRead` does not block the Read tool, so both layers are needed; scrubbing is honored only at user, managed or `--settings` level; the sandbox was beta.
  - Codex CLI: permission-profile deny-read globs (OS-level) and `shell_environment_policy`. Name patterns alone still passed a password embedded in `DATABASE_URL`; the documentation recommends starting from `inherit = "none"` or `"core"`. Setting `sandbox_mode` or passing `--sandbox` makes the profile ignored; profiles were beta.
  - agy: user-level `read_file(...)` deny rules and the terminal sandbox. Deny rules take no globs, match full paths and cover only the file-reading tool; the sandbox blocked only paths outside the workspace, so `.env*` and `*.pem` inside it stayed readable; there was no environment-variable filtering; the sandbox was a preview.

## Steps

1. **Identify the host.** Determine which agent host and version is running this session (for example from its `--version` output) and the operating system. Say which one you found before continuing.
2. **Read the current documentation.** Read that host's current official documentation on permissions, sandboxing and subprocess environment. Never rely on remembered setting keys or on the hints in Background; note the documentation pages and the date you read them.
3. **Propose user-level settings.** Draft changes to the user-level configuration only, with the target file path and the exact diff of the keys you change; replace the value of every existing secret-bearing entry that the diff or its context would show (for example environment-variable blocks, API keys, tokens, MCP server headers) with `<redacted>`. The goals: the agent cannot read `.env*`, private keys or certificate files (`*.pem`, `*.key` and similar) through its tools or through subprocesses, and subprocess environments exclude secret-bearing variables such as `DATABASE_URL` and `RABBITMQ_URL`. For each goal, state which mechanism covers it and what it does not cover.
4. **Wait for approval.** Show the proposal and stop until the user explicitly approves it. Treat silence, a question or a partial answer as not approved; apply only what was approved.
5. **Apply.** Back up each user-level file you change with a silent copy next to the original that keeps its permissions (for example `cp -p <file> <file>.bak-<YYYYMMDD>`), never inside this repository and never printed; tell the user that the backup holds whatever secrets the original holds and can be deleted once the change is confirmed. Then apply the approved diff. Tell the user if the host must be restarted for the settings to take effect, and wait for that before verifying.
6. **Verify with probes.** Probe without displaying any secret value. For the shell, run `wc -c < .env`, which prints only a byte count, and list only the names of the subprocess environment variables with `python3 -c 'import os; print(sorted(os.environ))'`, which never prints values even when a value spans several lines, to check that secret-bearing variables such as `DATABASE_URL` are absent. Probe the file-reading tool on `.env` only after the user confirms that the file holds no real secrets, because an unblocked read shows its contents. If the service has no `.env`, do not create one; report the file probes as not run. Report each probe and whether it was blocked.
7. **Run make check.** Run `make check` from the service root to confirm the protection does not break the quality checks: testcontainers needs the Docker socket and uv needs network access. If protection and `make check` conflict, report the exact failure and the options, and let the user decide; do not loosen the settings on your own.
8. **Report gaps.** List what remains unprotected (for example tool-level rules that subprocesses bypass, files inside the workspace that the sandbox still allows, environment variables the host cannot filter), the files you changed with their backups, and the documentation you relied on.

## Never

- Never write managed settings or any organization-wide policy file; this workflow changes user-level configuration only.
- Never create, modify or delete tracked files or configuration in this repository, including `.env` files, project-level host settings, `.gitignore` or the template-tracked skill; the only expected writes are the ignored build and test artifacts that `make check` itself produces (`.venv/`, `.coverage`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`).
- Never apply a change before the user's explicit approval, and never widen it beyond what was approved.
- Never print, copy or log real secret values beyond the silent backups made in Apply; probes report only whether access was blocked.
- Never print the contents of a user-level configuration file or its backup; show only the redacted diff.
- Never claim complete protection; host settings are a second line of defense behind keeping secrets out of the environment.
