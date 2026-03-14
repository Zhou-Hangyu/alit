# alit

Lightweight literature review system for AI coding agents. Zero dependencies. SQLite-only.

## Install

```bash
pip install alit
```

## Use

```bash
alit init
alit add "Attention Is All You Need" --year 2017 --abstract "..." --id vaswani2017attention
alit search "attention"
alit recommend 5
alit ask "What approaches exist for sequence modeling?" --depth 2
```

## Agent Integration

```bash
alit install-skill    # installs SKILL.md for opencode/Claude Code
```

See `alit --help` for all commands.
