# ECC for Gemini CLI

This file provides Gemini CLI with the baseline ECC workflow, review standards, and security checks for this repository.

## Overview

Everything Claude Code (ECC) is a cross-harness coding system with 36 specialized agents, 142 skills, and 68 commands.
These resources are installed locally in the `.ecc/` directory.

## Core Workflow

1. Plan before editing large features.
2. Prefer test-first changes for bug fixes and new functionality.
3. Review for security before shipping.
4. Keep changes self-contained, readable, and easy to revert.

## Coding Standards

- Prefer immutable updates over in-place mutation.
- Keep functions small and files focused.
- Validate user input at boundaries.
- Never hardcode secrets.
- Fail loudly with clear error messages instead of silently swallowing problems.

## Security Checklist

Before any commit:

- No hardcoded API keys, passwords, or tokens
- All external input validated
- Parameterized queries for database writes
- Sanitized HTML output where applicable
- Authz/authn checked for sensitive paths
- Error messages scrubbed of sensitive internals

## Delivery Standards

- Use conventional commits: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`
- Run targeted verification for touched areas before shipping
- Prefer contained local implementations over adding new third-party runtime dependencies

## ECC Resources (Available in .ecc/)

- `AGENTS.md`: Repo-wide operating rules.
- `skills/`: Deep workflow guidance.
- `commands/`: Slash-command patterns worth adapting into prompts/macros.
- `mcp-configs/`: Shared connector baselines.

---
**Usage Tip:** When performing complex tasks, refer to the specialized agents in `.ecc/agents/` and skills in `.ecc/skills/`.
