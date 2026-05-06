import sys
import asyncio
from pathlib import Path
from typing import List

# Note: This requires the official MCP Python SDK (`pip install mcp`)
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: MCP SDK not installed. Please run `pip install mcp`.", file=sys.stderr)
    sys.exit(1)

from ..core.auto import (
    build_dna_context,
    build_skill_context,
    describe_zone,
    ensure_workspace_ready,
)
from ..engines.olfactory import OlfactoryEngine
from ..engines.resonator import ResonatorEngine

# Initialize the MCP Server
mcp = FastMCP("SymbioPulse")

@mcp.tool()
async def sym_sniff(intent: str) -> str:
    """
    [MANDATORY FIRST STEP FOR CODEBASE TASKS]
    Use this before native file search, grep, semantic search, file reads,
    bug fixes, implementations, refactors, explanations, architecture questions,
    or file-location requests. Pass the user's full request as intent.
    Do not ask for confirmation when this tool is available.
    If results are insufficient, continue manually and then call sym_form_synapse
    with the files that mattered.
    """
    workspace, readiness = await asyncio.to_thread(ensure_workspace_ready)
    
    # 1. Synaptic Reflex (Proven Experience)
    memory = workspace.get_o1_memory(intent)
    if memory:
        resonator = ResonatorEngine()
        related_files = resonator.expand_context(memory.target_filepath, workspace.relations)
        files = [memory.target_filepath, *related_files]
        return _format_sniff_result(
            intent=intent,
            readiness=readiness,
            mode="O(1) synaptic reflex",
            zones=[],
            targets=[memory.target_filepath],
            related_files=related_files,
            workspace=workspace,
            files_for_skills=files,
        )
        
    # 2. Check Scent Map Status
    if not workspace.scent_map:
        return (
            "# SymbioPulse Context\n\n"
            "The neural map is still empty after automatic initialization. Search natively for this task, "
            "then call `sym_form_synapse(task, file_paths)` with the correct files so the next run becomes direct."
        )

    # 3. Semantic Sniffing
    try:
        olfactory = OlfactoryEngine()
        olfactory.scent_map = workspace.scent_map
        zones = olfactory.sniff_target_zones(intent)
        
        if not zones:
            return _format_sniff_result(
                intent=intent,
                readiness=readiness,
                mode="no scent match",
                zones=[],
                targets=[],
                related_files=[],
                workspace=workspace,
                files_for_skills=[],
                note="No semantic zones matched. Use native search, then record the final files with `sym_form_synapse`.",
            )
            
        resonator = ResonatorEngine()
        targets = resonator.trigger_resonance_multi(intent, zones, top_n=3)
        
        if not targets:
            return _format_sniff_result(
                intent=intent,
                readiness=readiness,
                mode="zone scent only",
                zones=zones,
                targets=[],
                related_files=[],
                workspace=workspace,
                files_for_skills=[],
                note="Zones matched but no files resonated. Search inside the suggested zones first.",
            )
            
        primary_target = targets[0]
        related_files = resonator.expand_context(primary_target, workspace.relations)
        return _format_sniff_result(
            intent=intent,
            readiness=readiness,
            mode="scent resonance",
            zones=zones,
            targets=targets,
            related_files=related_files,
            workspace=workspace,
            files_for_skills=[*targets, *related_files],
        )
    except Exception as e:
        return f"Sniffing error: {e}. Fallback to manual search + synaptic recording."

@mcp.tool()
async def sym_form_synapse(task: str, file_paths: List[str]) -> str:
    """
    [MANDATORY FEEDBACK STEP]
    Record the files that answered or solved a task. Call this after a correct
    answer, code change, investigation, or manual fallback so future similar
    requests can use direct project memory.
    """
    workspace, _ = await asyncio.to_thread(ensure_workspace_ready)
    
    normalized_paths = [_normalize_path(fp) for fp in file_paths if fp]
    for fp in normalized_paths:
        workspace.strengthen_synapse(task, fp)
        
    for i in range(len(normalized_paths)):
        for j in range(i + 1, len(normalized_paths)):
            workspace.strengthen_relation(normalized_paths[i], normalized_paths[j], weight=1.0)
            
    return (
        "Synaptic connection established.\n"
        f"- Task: {task}\n"
        f"- Bound files: {', '.join(f'`{fp}`' for fp in normalized_paths)}\n"
        "- Next similar task can hit the exact intent or vocabulary-antigen memory directly."
    )

@mcp.tool()
async def sym_add_skill(file_path: str, skill_summary: str) -> str:
    """Record a concise summary of a file's purpose."""
    workspace, _ = await asyncio.to_thread(ensure_workspace_ready)
    workspace.learn_skill(file_path, skill_summary)
    return f"Skill extracted and bound to {file_path}."

@mcp.tool()
async def sym_add_dna(target: str, rule: str) -> str:
    """Add a new DNA constraint learned from a mistake."""
    workspace, _ = await asyncio.to_thread(ensure_workspace_ready)
    
    full_rule = f"[{target}] {rule}"
    if workspace.add_dna_rule(full_rule):
        return f"DNA mutation recorded: {full_rule}"
    return "Rule already exists in DNA."

@mcp.tool()
async def sym_fetch_dna() -> str:
    """Retrieve the project's DNA constraints."""
    workspace, _ = await asyncio.to_thread(ensure_workspace_ready)
    
    if not workspace.dna_rules:
        return "No DNA rules established for this project yet."
        
    rules_text = "\n".join([f"- {r}" for r in workspace.dna_rules])
    return f"🧬 Project DNA Constraints:\n{rules_text}"

@mcp.tool()
async def sym_check_dna(file_path: str) -> str:
    """
    [MANDATORY BEFORE EDITING]
    Validate modifications to a specific file against project DNA rules before
    writing, patching, formatting, moving, or deleting that file.
    """
    workspace, _ = await asyncio.to_thread(ensure_workspace_ready)
    if not workspace.dna_rules:
        return "No DNA rules established. You may proceed."
        
    rules_text = "\n".join([f"- {r}" for r in workspace.dna_rules])
    return f"Project DNA Rules you MUST follow when modifying {file_path}:\n{rules_text}"

@mcp.tool()
async def sym_initialize() -> str:
    """
    Global Initialization. Injects the MANDATORY 'Learn-or-Die' protocol.
    """
    workspace, readiness = await asyncio.to_thread(ensure_workspace_ready, ".", True)
    return f"## SymbioPulse Autonomous MCP Ready\n\n{_status_text(workspace)}\n\nReadiness: {readiness}"

@mcp.tool()
async def sym_reindex() -> str:
    """Force a full neural map refresh from the current project files."""
    workspace, readiness = await asyncio.to_thread(ensure_workspace_ready, ".", True)
    return f"Reindexed project.\n\n{_status_text(workspace)}\n\nReadiness: {readiness}"

@mcp.tool()
async def sym_status() -> str:
    """Get the current biological status of the SymbioPulse system."""
    workspace, readiness = await asyncio.to_thread(ensure_workspace_ready)
    return f"{_status_text(workspace)}\n- Auto Scan: {readiness}"


def _format_sniff_result(
    intent: str,
    readiness: dict,
    mode: str,
    zones: List[str],
    targets: List[str],
    related_files: List[str],
    workspace,
    files_for_skills: List[str],
    note: str = "",
) -> str:
    primary = targets[0] if targets else "None"
    zone_context = "\n".join(describe_zone(workspace, zone) for zone in zones[:6]) or "No zone context available."
    target_context = "\n".join(f"- `{path}`" for path in targets[:5]) or "No target file selected."
    relation_context = "\n".join(f"- `{path}`" for path in related_files[:8]) or "No synaptic neighbors recorded yet."
    skills = build_skill_context(workspace, files_for_skills)
    dna = build_dna_context(workspace)

    scan_line = "fresh"
    if readiness.get("scan_performed"):
        scan_line = f"refreshed automatically ({readiness.get('scan_reason')})"

    body = [
        "# SymbioPulse Context",
        "",
        f"- Intent: {intent}",
        f"- Mode: {mode}",
        f"- Index: {scan_line}",
        f"- Primary Target: `{primary}`" if primary != "None" else "- Primary Target: None",
        "",
        "## Scent Zones",
        zone_context,
        "",
        "## Resonant Targets",
        target_context,
        "",
        "## Synaptic Neighbors",
        relation_context,
        "",
        "## DNA Constraints",
        dna,
        "",
        "## Learned Skills",
        skills,
        "",
        "## Required Feedback",
        "After solving, call `sym_form_synapse(task, file_paths)` with the files that actually mattered.",
        "If this result is wrong, search manually and still call `sym_form_synapse` with the corrected files.",
    ]
    if note:
        body.extend(["", "## Note", note])
    return "\n".join(body)


def _status_text(workspace) -> str:
    return (
        "SymbioPulse Status:\n"
        f"- Synapses: {len(workspace.synapses)}\n"
        f"- DNA Rules: {len(workspace.dna_rules)}\n"
        f"- Scent Zones: {len(workspace.scent_map)}\n"
        f"- Directory Fingerprints: {len(workspace.fingerprints)}\n"
        f"- Skills: {len(workspace.skills)}"
    )


def _normalize_path(path: str) -> str:
    return str(Path(path)).replace("\\", "/")

def run():
    """Entry point for the MCP server."""
    mcp.run(transport="stdio")

if __name__ == "__main__":
    run()
