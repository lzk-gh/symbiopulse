<!-- symbiopulse:managed:start -->
# SymbioPulse Autonomous MCP Protocol

Audience: Claude Code.

This project uses SymbioPulse as the MCP-native memory and context layer. When the `symbiopulse` MCP server is available, use it as the first source of project context.

## Required Workflow

1. Call `sym_sniff(intent)` before broad manual search.
2. Before editing a target file, call `sym_check_dna(file_path)`.
3. After a correct solution, call `sym_form_synapse(task, file_paths)` with the files that mattered.
4. When a reusable implementation fact is discovered, call `sym_add_skill(file_path, skill_summary)`.
5. When a mistake creates a durable constraint, call `sym_add_dna(target, rule)`.

## Fallback

If MCP tools are not available in the current client, proceed with native code search and mention that SymbioPulse was unavailable. Do not invent MCP results.
<!-- symbiopulse:managed:end -->
