---
name: fast-ddd-init
description: Create a new fast-ddd backend service from the fast-ddd copier template at the git tag matching this plugin's version. Use only when the user explicitly invokes it to create a service.
disable-model-invocation: true
---

# Create a fast-ddd service

Create one service repository with Copier. Run every step in order and stop at the first failure; never fall back to another version, source, or template location.

## 1. Template source

- Template version: `0.1.0`
- Template source: `https://github.com/benwu95/fast-ddd-service`

Use the template version as `<version>`; the template tag is `v<version>`. Use the template source as `<source>`. Both values ship with this plugin version, and the framework's `make check` keeps them equal to the template it tags; do not read any file to look them up or replace them.

Use `<source>` as the Copier source, never this plugin's installed directory. Copier records the source in `.copier-answers.yml`; the plugin directory is a versioned cache that hosts delete after upgrades, and `copier update` fails once the recorded source is gone.

## 2. Confirm the inputs

Ask the user for:

- **Service name**: lowercase words separated by hyphens, matching `^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$` (for example `orders-service`).
- **Destination directory**: a path that does not exist or is an empty directory. Suggest `./<service name>`.

Show the service name, destination, `<source>`, and tag `v<version>`, then wait for the user's explicit confirmation before running any command. If the destination exists and is not empty, stop and ask for another destination; never write into it.

## 3. Check prerequisites

- `uv --version` succeeds.
- `git ls-remote "<source>" "refs/tags/v<version>"` prints the tag.
  - Authentication failure: the repository is private. Tell the user to configure Git credentials for HTTPS (for example `gh auth setup-git`) and stop.
  - No output: the tag is not published. Report it and stop.

## 4. Create the service

```sh
uvx --python 3.13.12 --from copier==9.19.1 copier copy \
  --vcs-ref "v<version>" --defaults \
  -d service_name="<service name>" \
  "<source>" "<destination>"
```

The command needs network access and writes outside the destination: uv's cache and tool directories, and Copier's Git cache. If the host sandbox blocks any of them, ask the user to approve running the command outside the sandbox. If Copier fails (for example the name is rejected or the network fails), report its output and stop.

## 5. Verify the answers

Read `<destination>/.copier-answers.yml` and confirm that `_src_path` equals `<source>` and `_commit` equals `v<version>`. Report any mismatch to the user.

## 6. Hand over

Tell the user to:

1. Open a new agent session in `<destination>`; the service's own `fast-ddd` skill loads only in a session started there.
2. Follow `docs/template-operations.md` in the new service to create the lock, sync the environment, and run `make check`.
3. Ask the service's `fast-ddd` skill to set up secret protection for this host before using real configuration. If that skill does not offer a secret-protection workflow yet, tell the user that host-level secret protection is not set up and that the template no longer ships host permission settings.
