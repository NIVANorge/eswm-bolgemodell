# Copilot Instructions

## Package Management
- Use **Pixi** for environment, dependencies, and tasks.
- Prefer `pixi add`, `pixi run`, and `pixi task` over pip/poetry/conda.
- Assume a working `pixi.toml` exists unless stated otherwise.

## Code Style
- Keep answers **short, direct, and actionable**.
- Prefer examples over explanations.
- No unnecessary commentary or background.

## Python
- Target modern Python (3.11+ unless specified).
- Follow PEP 8.
- Use type hints when helpful, but keep concise.

## CLI & Commands
- Show exact commands when relevant.
- Use fenced code blocks.
- Avoid describing obvious command behavior.

## Explanations
- Default to **≤5 bullet points**.
- No repetition.
- Only explain what is strictly necessary to proceed.

## Assumptions
- Developer audience.
- Linux/macOS unless stated otherwise.
- Sensible defaults over configurability.

## When Uncertain
- Make a reasonable assumption and proceed.
- State assumptions briefly in one line.