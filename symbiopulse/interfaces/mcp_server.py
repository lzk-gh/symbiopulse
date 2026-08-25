import asyncio
import contextvars
import functools
import sys
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
    schedule_workspace_refresh,
)
from ..engines.olfactory import OlfactoryEngine
from ..engines.resonator import ResonatorEngine
from ..indexing.path_filter import PathFilter

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
    workspace, readiness = await _open_snapshot()
    refresh = schedule_workspace_refresh()
    if refresh.get("scheduled") or refresh.get("index_state") == "indexing":
        readiness.update(refresh)
    
    # 1. Synaptic Reflex (Proven Experience)
    memory = workspace.get_o1_memory(intent)
    if memory and _is_valid_memory_target(workspace.root, memory.target_filepath):
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
            "The neural map is warming up in the background; this query did not wait for a workspace scan. "
            f"Job: `{refresh['job_id']}`. Search natively for this task, then call "
            "`sym_form_synapse(task, file_paths)` with the correct files so the next run becomes direct."
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
        targets = resonator.trigger_resonance_multi(
            intent,
            zones,
            top_n=3,
            fingerprints=workspace.fingerprints,
        )
        
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
    workspace, _ = await _open_snapshot()

    path_filter = PathFilter(str(workspace.root))
    normalized_paths = []
    errors = []
    for file_path in file_paths:
        normalized, error = _normalize_path(file_path, workspace.root, path_filter)
        if error:
            errors.append(f"`{file_path}`: {error}")
        elif normalized and normalized not in normalized_paths:
            normalized_paths.append(normalized)

    if normalized_paths:
        await _run_sync(workspace.record_feedback, task, normalized_paths)

    error_text = ""
    if errors:
        error_text = "\n- Rejected: " + "; ".join(errors)
            
    return (
        "Synaptic connection established.\n"
        f"- Task: {task}\n"
        f"- Bound files: {', '.join(f'`{fp}`' for fp in normalized_paths)}\n"
        "- Next similar task can hit the exact intent or vocabulary-antigen memory directly."
        f"{error_text}"
    )

@mcp.tool()
async def sym_add_skill(file_path: str, skill_summary: str) -> str:
    """Record a concise summary of a file's purpose."""
    workspace, _ = await _open_snapshot()
    await _run_sync(workspace.learn_skill, file_path, skill_summary)
    return f"Skill extracted and bound to {file_path}."

@mcp.tool()
async def sym_add_dna(target: str, rule: str) -> str:
    """Add a new DNA constraint learned from a mistake."""
    workspace, _ = await _open_snapshot()
    
    full_rule = f"[{target}] {rule}"
    if await _run_sync(workspace.add_dna_rule, full_rule):
        return f"DNA mutation recorded: {full_rule}"
    return "Rule already exists in DNA."

@mcp.tool()
async def sym_fetch_dna() -> str:
    """Retrieve the project's DNA constraints."""
    workspace, _ = await _open_snapshot()
    
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
    workspace, _ = await _open_snapshot()
    if not workspace.dna_rules:
        return "No DNA rules established. You may proceed."
        
    rules_text = "\n".join([f"- {r}" for r in workspace.dna_rules])
    return f"Project DNA Rules you MUST follow when modifying {file_path}:\n{rules_text}"

@mcp.tool()
async def sym_initialize() -> str:
    """
    Global Initialization. Injects the MANDATORY 'Learn-or-Die' protocol.
    """
    workspace, readiness = await _open_snapshot()
    refresh = schedule_workspace_refresh(force=not bool(workspace.scent_map))
    readiness.update(refresh)
    return f"## SymbioPulse Autonomous MCP Ready\n\n{_status_text(workspace)}\n\nReadiness: {readiness}"

@mcp.tool()
async def sym_reindex() -> str:
    """Force a full neural map refresh from the current project files."""
    workspace, readiness = await _open_snapshot()
    refresh = schedule_workspace_refresh(force=True)
    readiness.update(refresh)
    return f"Reindex scheduled.\n\n{_status_text(workspace)}\n\nReadiness: {readiness}"

@mcp.tool()
async def sym_status() -> str:
    """Get the current biological status of the SymbioPulse system."""
    workspace, readiness = await _open_snapshot()
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

    scan_line = readiness.get("index_state", "ready")
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


async def _open_snapshot():
    return await _run_sync(ensure_workspace_ready, ".", False, False)


async def _run_sync(function, *args):
    """Python 3.8-compatible equivalent of asyncio.to_thread()."""
    if hasattr(asyncio, "to_thread"):
        return await asyncio.to_thread(function, *args)
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    call = functools.partial(context.run, function, *args)
    return await loop.run_in_executor(None, call)


def _normalize_path(path: str, root: Path, path_filter: PathFilter):
    if not path:
        return None, "empty path"
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=False)
        relative = resolved.relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None, "PATH_OUTSIDE_ROOT"
    if not resolved.is_file():
        return None, "path does not identify an existing file"
    reason = path_filter.ignore_reason(candidate, is_dir=False)
    if reason:
        return None, f"PATH_IGNORED ({reason})"
    return relative, None


def _is_valid_memory_target(root: Path, path: str) -> bool:
    path_filter = PathFilter(str(root))
    normalized, error = _normalize_path(path, root, path_filter)
    return normalized is not None and error is None

def run():
    """Entry point for the MCP server."""
    mcp.run(transport="stdio")

if __name__ == "__main__":
    run()
