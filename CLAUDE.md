# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

TODO: 프로젝트 소개

## Agent rules (binding — see AGENTS.md)

`AGENTS.md` at the repo root defines rules for AI agents; follow them:

- **Never run `git commit` / `git push` / create PRs on the user's behalf** unless explicitly told to. After work, report only: changed files, verification results, next steps.
- **Verify before reporting.** Python changes: at minimum a syntax check.
- **Korean + English + digits only** — no Chinese/Japanese characters anywhere (check with `rg '[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]'` per AGENTS.md — must return 0 hits).
- Work in small cycles: ≤5–6 files per change(maximum 10 files), then verify and report.
- Commit/PR tone is collaborative, no emoji in PR titles/bodies; PRs use the 8-section template in `.github/pull_request_template.md`.
- Security (`.github/copilot-instructions.md`, `.claudeignore`): never read `.env*`, `*.tfvars`, `*.pem`/keys; no hardcoded secrets; mask PII.

## Repository layout

TODO: 설계 후 작성

## Python workspace

A `uv` workspace rooted at `pyproject.toml` with members; Python pinned to `>=3.11,<3.12`.

```bash
uv sync
uv run pre-commit install

uv run ruff check .              # lint (CI gate); isort known-first-party=["backend"]
uv run ruff format .             # CI runs `ruff format --check .`
uv lock --check                  # lockfile sync (CI gate)
# TODO: pytest랑 uv run uvicorn --reload 등 명령어 추가
```

Each service pyproject sets `pythonpath = ["src"]`, `testpaths = ["tests"]`, `test_*.py` discovery. CI falls back to an import check when a service has no tests.

## Conventions

Commits follow `type: 제목 (#이슈번호)` with types `feat`, `fix`, `refactor`, `chore`, `test`, `docs`, `style`. Issues use `.github/ISSUE_TEMPLATE/`.
TODO: .env룰이나 보안 규칙 등 룰 추가

## Code generation constraints

- Ensure all recommended external packages are safe from known CVE vulnerabilities.
- Filter out local network IPs and staging/production domain names from error logs.
