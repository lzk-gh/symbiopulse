# SymbioPulse: MCP-Native Neural Memory for Codebases

SymbioPulse is an MCP-first context layer for AI coding agents. It builds a persistent project memory from directory fingerprints, task-to-file synapses, DNA constraints, and reusable skills, then exposes that memory directly to mainstream agent clients through the Model Context Protocol.

The developer should only need to load the MCP server. Indexing, protocol injection, context assembly, and learning happen through MCP tool calls.

## Core Loop

1. **Environmental Pruning:** Ignore runtime noise such as `.git`, `.symbio`, `.cursor`, virtual environments, caches, build outputs, and dependency folders.
2. **Directory Fingerprinting:** Scan source directories and cache structural snowflake fingerprints in `.symbio/fingerprints.json`.
3. **Context Perception:** Convert fingerprints into scent zones in `.symbio/scents.json`.
4. **Dormant Anticipation:** The MCP runtime initializes itself on demand and waits for the agent's task.
5. **Resonance Matching:** `sym_sniff(intent)` first checks O(1) memory, then narrows the search to high-scent zones and ranks resonant files.
6. **Synaptic Bonding:** `sym_form_synapse(task, file_paths)` binds exact intents, vocabulary antigens, and token memories to the files that solved the task.
7. **Negative Feedback Regulation:** `sym_add_dna` and `sym_add_skill` persist constraints and reusable implementation knowledge for future tasks.

## MCP Tools

| Tool | Purpose |
| :--- | :--- |
| `sym_sniff(intent)` | Primary context entry. Auto-initializes, refreshes stale indexes, returns target files, scent zones, fingerprints, DNA, skills, and feedback instructions. |
| `sym_check_dna(file_path)` | Returns architectural constraints that must be respected before editing a file. |
| `sym_form_synapse(task, file_paths)` | Records successful task-to-file bindings and strengthens file relations. |
| `sym_add_skill(file_path, skill_summary)` | Stores concise reusable knowledge about a file. |
| `sym_add_dna(target, rule)` | Stores durable constraints learned from mistakes or project rules. |
| `sym_fetch_dna()` | Returns all recorded DNA constraints. |
| `sym_status()` | Shows current memory, scent, fingerprint, and skill counts. |
| `sym_initialize()` | Forces initialization and protocol injection. Usually optional because tools self-initialize. |
| `sym_reindex()` | Forces a full project reindex. |

## Agent Support

SymbioPulse is not Cursor-specific. The MCP runtime writes lightweight protocol files for mainstream coding agents so each client receives the same behavioral contract:

| Agent surface | Protocol file |
| :--- | :--- |
| Codex / OpenAI agents | `AGENTS.md` |
| Claude Code | `CLAUDE.md` |
| Gemini agents | `GEMINI.md` |
| Cursor | `.cursor/rules/symbiopulse.mdc`, `.cursorrules` |
| GitHub Copilot | `.github/copilot-instructions.md` |
| Windsurf | `.windsurfrules` |
| Cline | `.clinerules` |

Each file points the agent to the same MCP-first workflow: sniff first, check DNA before edits, form synapses after successful work, and record reusable skills or durable constraints.

## Installation

### MCP Clients

```json
{
  "mcpServers": {
    "symbiopulse": {
      "command": "uvx",
      "args": ["symbiopulse", "sym-mcp"]
    }
  }
}
```

### Local Development

```bash
pip install -e .
sym-mcp
```

## Runtime State

SymbioPulse writes project-local memory under `.symbio/`:

- `scents.json`: directory scent map.
- `fingerprints.json`: structural directory fingerprints.
- `synapses.json`: exact, antigen, and token task memories.
- `relations.json`: file-to-file affinity graph.
- `dna.json`: project constraints.
- `skills.json`: learned file summaries.

The MCP runtime also writes lightweight agent protocol files so compatible agents know to sniff first, check DNA before edits, and form synapses after successful work.

## Architecture

1. **Neural Core:** `.symbio` state, synapses, DNA, relations, and fingerprints.
2. **Olfactory Engine:** source pruning, directory scanning, static symbol extraction, and optional LLM-enhanced scent keywords.
3. **Resonator Engine:** file-level resonance ranking inside scented zones.
4. **Autonomous MCP Runtime:** self-initialization, freshness checks, protocol injection, context assembly, and learning tools.

There is no separate user-facing workflow or background watcher. MCP is the product surface.
