import hashlib
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from filelock import FileLock, Timeout

from ..engines.olfactory import OlfactoryEngine
from ..indexing.path_filter import ScanBudgetExceeded
from .genome import SymbioWorkspace


@dataclass(frozen=True)
class AgentProtocol:
    name: str
    path: str
    content: str
    prefix: str = ""


MANAGED_BLOCK_START = "<!-- symbiopulse:managed:start -->"
MANAGED_BLOCK_END = "<!-- symbiopulse:managed:end -->"


@dataclass
class _ProjectRuntime:
    root: Path
    workspace: SymbioWorkspace
    lock: threading.RLock
    state_signature: Tuple[Tuple[int, int], ...] = ()
    loaded: bool = False
    protocol_injected: bool = False
    index_state: str = "ready"
    scan_reason: str = ""
    pending_force: bool = False
    last_refresh_requested: float = 0.0


_RUNTIMES: Dict[str, _ProjectRuntime] = {}
_RUNTIMES_LOCK = threading.RLock()
_INDEX_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="symbiopulse-index")
_INDEX_JOBS: Dict[str, Future] = {}


def agent_protocols() -> List[AgentProtocol]:
    """Known rule files used by mainstream coding agents and IDE assistants."""
    return [
        AgentProtocol("Codex / OpenAI agents", "AGENTS.md", _markdown_protocol("Codex / OpenAI agents")),
        AgentProtocol("Claude Code", "CLAUDE.md", _markdown_protocol("Claude Code")),
        AgentProtocol("Gemini agents", "GEMINI.md", _markdown_protocol("Gemini agents")),
        AgentProtocol("Cursor rules", ".cursor/rules/symbiopulse.mdc", _markdown_protocol("Cursor"), _cursor_mdc_header()),
        AgentProtocol("Cursor legacy", ".cursorrules", _plain_rules_protocol()),
        AgentProtocol("GitHub Copilot", ".github/copilot-instructions.md", _markdown_protocol("GitHub Copilot")),
        AgentProtocol("Windsurf", ".windsurfrules", _plain_rules_protocol()),
        AgentProtocol("Cline", ".clinerules", _plain_rules_protocol()),
    ]


def ensure_workspace_ready(
    root_dir: str = ".",
    force_scan: bool = False,
    scan_if_missing: bool = True,
) -> Tuple[SymbioWorkspace, Dict[str, object]]:
    """
    Open the last complete local snapshot. Native callers may opt into a bounded initial
    scan; MCP query handlers pass ``scan_if_missing=False`` so reads never walk the tree.
    """
    root = Path(root_dir).resolve()
    runtime = _get_runtime(root)
    with runtime.lock:
        workspace = runtime.workspace
        if not workspace.is_initialized():
            workspace = SymbioWorkspace(str(root))
            runtime.workspace = workspace
            runtime.loaded = False
            runtime.state_signature = ()
            runtime.protocol_injected = False
            workspace.init_workspace()
        signature = _state_signature(workspace)
        if not runtime.loaded or signature != runtime.state_signature:
            workspace.load_state()
            workspace.compact_rules()
            runtime.state_signature = _state_signature(workspace)
            runtime.loaded = True

    snapshot_state = "ready" if workspace.scent_map and workspace.fingerprints else "warming_up"
    with _RUNTIMES_LOCK:
        index_state = runtime.index_state if runtime.index_state in {"indexing", "degraded"} else snapshot_state
        status: Dict[str, object] = {
            "initialized": True,
            "scan_performed": False,
            "scan_reason": runtime.scan_reason,
            "index_state": index_state,
            "job_id": _job_id(root) if index_state == "indexing" else None,
        }

    if force_scan or (scan_if_missing and status["index_state"] == "warming_up"):
        scan_status = _scan_workspace(root, force=force_scan)
        status.update(scan_status)
        with _RUNTIMES_LOCK:
            runtime.index_state = scan_status.get("index_state", "degraded")
            runtime.scan_reason = scan_status.get("scan_reason", "")
        if scan_status.get("scan_performed"):
            with runtime.lock:
                workspace.load_state()
                runtime.state_signature = _state_signature(workspace)
                runtime.loaded = True

    with runtime.lock:
        if not runtime.protocol_injected:
            status["protocol_files"] = inject_agent_protocol(str(root))
            runtime.protocol_injected = True
        else:
            status["protocol_files"] = []
    return workspace, status


def schedule_workspace_refresh(
    root_dir: str = ".",
    force: bool = False,
    min_interval_seconds: float = 300.0,
) -> Dict[str, object]:
    """Submit an idempotent process-local refresh; a cross-process lock elects one scanner."""
    root = Path(root_dir).resolve()
    key = str(root)
    with _RUNTIMES_LOCK:
        runtime = _get_runtime(root)
        existing = _INDEX_JOBS.get(key)
        if existing is not None and not existing.done():
            if force:
                runtime.pending_force = True
            return {
                "index_state": "indexing",
                "job_id": _job_id(root),
                "scheduled": False,
                "queued_force": runtime.pending_force,
            }
        now = time.monotonic()
        if not force and now - runtime.last_refresh_requested < min_interval_seconds:
            return {
                "index_state": runtime.index_state,
                "job_id": None,
                "scheduled": False,
                "queued_force": False,
            }
        runtime.last_refresh_requested = now
        runtime.index_state = "indexing"
        runtime.scan_reason = ""
        future = _INDEX_EXECUTOR.submit(_run_scheduled_scan, root, force)
        _INDEX_JOBS[key] = future
    return {
        "index_state": "indexing",
        "job_id": _job_id(root),
        "scheduled": True,
        "queued_force": False,
    }


def _run_scheduled_scan(root: Path, force: bool) -> Dict[str, object]:
    result = _scan_workspace(root, force)
    key = str(root)
    with _RUNTIMES_LOCK:
        runtime = _get_runtime(root)
        rerun_force = runtime.pending_force and not force
        runtime.pending_force = False
        runtime.index_state = result.get("index_state", "degraded")
        runtime.scan_reason = result.get("scan_reason", "")
        if rerun_force:
            runtime.index_state = "indexing"
            future = _INDEX_EXECUTOR.submit(_run_scheduled_scan, root, True)
            _INDEX_JOBS[key] = future
        else:
            _INDEX_JOBS.pop(key, None)
    return result


def _get_runtime(root: Path) -> _ProjectRuntime:
    key = str(root)
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.get(key)
        if runtime is None:
            runtime = _ProjectRuntime(root, SymbioWorkspace(str(root)), threading.RLock())
            _RUNTIMES[key] = runtime
        return runtime


def _scan_workspace(root: Path, force: bool = False) -> Dict[str, object]:
    workspace = SymbioWorkspace(str(root))
    workspace.symbio_dir.mkdir(exist_ok=True)
    scan_lock = FileLock(workspace.scan_lock_file)
    try:
        scan_lock.acquire(timeout=0)
    except Timeout:
        return {
            "scan_performed": False,
            "scan_reason": "another process owns the index scan",
            "index_state": "indexing",
        }

    try:
        workspace.load_state()
        olfactory = OlfactoryEngine(root_dir=str(root))
        scent_map, mtime_map = olfactory.scan(
            workspace.scent_map,
            workspace.mtime_map,
            mode="full" if force else "standard",
            workspace=workspace,
        )
        workspace.scent_map = scent_map
        workspace.mtime_map = mtime_map
        workspace.fingerprints = olfactory.fingerprint_map
        _prune_stale_relations(root, workspace)
        workspace.compact_relations()
        workspace.publish_index_state(
            scent_map,
            olfactory.fingerprint_map,
            mtime_map,
            workspace.relations,
        )
        return {
            "scan_performed": True,
            "scan_reason": "forced" if force else "initial snapshot missing",
            "index_state": "ready",
        }
    except ScanBudgetExceeded as error:
        return {
            "scan_performed": False,
            "scan_reason": str(error),
            "index_state": "degraded",
        }
    except Exception as error:
        return {
            "scan_performed": False,
            "scan_reason": f"scan failed: {error}",
            "index_state": "degraded",
        }
    finally:
        scan_lock.release()


def _state_signature(workspace: SymbioWorkspace) -> Tuple[Tuple[int, int], ...]:
    paths = (
        workspace.synapse_file,
        workspace.dna_file,
        workspace.scent_file,
        workspace.fingerprint_file,
        workspace.skills_file,
        workspace.mtime_file,
        workspace.relations_file,
    )
    signature = []
    for path in paths:
        try:
            stat_result = path.stat()
            signature.append((stat_result.st_mtime_ns, stat_result.st_size))
        except OSError:
            signature.append((0, 0))
    return tuple(signature)


def _job_id(root: Path) -> str:
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    return f"index:{digest}"


def inject_agent_protocol(root_dir: str = ".") -> List[str]:
    """Writes managed SymbioPulse instructions without replacing user-authored content."""
    written: List[str] = []
    for protocol in agent_protocols():
        target = Path(root_dir) / protocol.path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            exists = target.exists()
            current = target.read_text(encoding="utf-8", errors="ignore") if exists else ""
            next_content = _merge_managed_protocol_block(
                current=current,
                protocol=protocol,
                exists=exists,
            )
            if not exists or current != next_content:
                target.write_text(next_content, encoding="utf-8")
            written.append(protocol.path)
        except Exception:
            continue
    return written


def _merge_managed_protocol_block(current: str, protocol: AgentProtocol, exists: bool) -> str:
    block = _managed_block(protocol.content)
    if not exists or not current.strip():
        return f"{protocol.prefix}{block}"

    start = current.find(MANAGED_BLOCK_START)
    end = current.find(MANAGED_BLOCK_END)
    if start >= 0 and end >= start:
        end += len(MANAGED_BLOCK_END)
        suffix = current[end:]
        if not suffix.strip():
            suffix = ""
        elif suffix.startswith("\r\n"):
            suffix = suffix[2:]
        elif suffix.startswith("\n"):
            suffix = suffix[1:]
        return f"{current[:start]}{block}{suffix}"

    return f"{current.rstrip()}\n\n{block}"


def _managed_block(content: str) -> str:
    return f"{MANAGED_BLOCK_START}\n{content.rstrip()}\n{MANAGED_BLOCK_END}\n"


def build_dna_context(workspace: SymbioWorkspace, limit: int = 12) -> str:
    if not workspace.dna_rules:
        return "No DNA rules are currently recorded."
    rules = workspace.dna_rules[:limit]
    return "\n".join(f"- {rule}" for rule in rules)


def build_skill_context(workspace: SymbioWorkspace, file_paths: List[str], limit: int = 8) -> str:
    lines: List[str] = []
    seen = set()
    for path in file_paths:
        if path in seen:
            continue
        seen.add(path)
        summary = workspace.skills.get(path)
        if summary:
            lines.append(f"- `{path}`: {summary}")
        if len(lines) >= limit:
            break
    return "\n".join(lines) if lines else "No learned skills are bound to these files yet."


def describe_zone(workspace: SymbioWorkspace, zone: str) -> str:
    fingerprint = workspace.fingerprints.get(zone, {})
    keywords = workspace.scent_map.get(zone, [])
    if not fingerprint:
        return f"- `{zone}`: keywords={', '.join(keywords[:8])}"

    symbols = ", ".join(fingerprint.get("symbols", [])[:8]) or "none"
    files = ", ".join(fingerprint.get("files", [])[:8]) or "none"
    scent = ", ".join(keywords[:8] or fingerprint.get("keywords", [])[:8])
    return (
        f"- `{zone}`: fingerprint={fingerprint.get('fingerprint', 'unknown')}, "
        f"files={fingerprint.get('file_count', 0)}, scent={scent}, "
        f"symbols={symbols}, sample_files={files}"
    )


def _prune_stale_relations(root: Path, workspace: SymbioWorkspace) -> None:
    valid_sources = {
        path
        for path in workspace.relations
        if (root / path).exists()
    }
    pruned: Dict[str, Dict[str, float]] = {}
    for source in valid_sources:
        targets = {
            target: weight
            for target, weight in workspace.relations.get(source, {}).items()
            if target in valid_sources and (root / target).exists()
        }
        if targets:
            pruned[source] = targets
    workspace.relations = pruned


def _cursor_mdc_header() -> str:
    return (
        "---\n"
        "description: SymbioPulse autonomous MCP protocol\n"
        "globs: **/*\n"
        "alwaysApply: true\n"
        "---\n"
    )


def _markdown_protocol(agent_name: str) -> str:
    return (
        "# SymbioPulse Autonomous MCP Protocol\n\n"
        f"Audience: {agent_name}.\n\n"
        "This project uses SymbioPulse as the MCP-native memory and context layer. "
        "When the `symbiopulse` MCP server is available, use it automatically as the first source of project context.\n\n"
        "## Mandatory Tool Use\n\n"
        "For every codebase question, bug fix, implementation, refactor, explanation, architecture question, "
        "or file-location request in this workspace:\n\n"
        "1. First call `sym_sniff(intent)` with the user's full request before native file search, grep, semantic search, "
        "file reads, or broad code exploration.\n"
        "2. Do not ask whether to use SymbioPulse. Use it automatically when the `symbiopulse` MCP server is available.\n"
        "3. Before editing any target file, call `sym_check_dna(file_path)` for that exact path.\n"
        "4. After a correct answer, investigation, or code change, call `sym_form_synapse(task, file_paths)` "
        "with the files that mattered.\n"
        "5. When a reusable implementation fact is discovered, call `sym_add_skill(file_path, skill_summary)`.\n"
        "6. When a mistake creates a durable constraint, call `sym_add_dna(target, rule)`.\n\n"
        "## Fallback\n\n"
        "If MCP tools are not available in the current client, state that SymbioPulse was unavailable, then proceed "
        "with native code search. If `sym_sniff` returns no useful target, continue with native search and still call "
        "`sym_form_synapse` after the relevant files are known. Do not invent MCP results.\n"
    )


def _plain_rules_protocol() -> str:
    return (
        "SymbioPulse Autonomous MCP Protocol\n\n"
        "Use the `symbiopulse` MCP server automatically as the first source of project context when available.\n\n"
        "Mandatory tool use:\n"
        "1. First call `sym_sniff(intent)` with the user's full request before native file search, grep, semantic search, "
        "file reads, or broad code exploration.\n"
        "2. Do not ask whether to use SymbioPulse. Use it automatically when the MCP server is available.\n"
        "3. Before editing any target file, call `sym_check_dna(file_path)` for that exact path.\n"
        "4. After a correct answer, investigation, or code change, call `sym_form_synapse(task, file_paths)` "
        "with the files that mattered.\n"
        "5. When a reusable implementation fact is discovered, call `sym_add_skill(file_path, skill_summary)`.\n"
        "6. When a mistake creates a durable constraint, call `sym_add_dna(target, rule)`.\n\n"
        "Fallback: if MCP tools are unavailable, state that SymbioPulse was unavailable, then use native code search. "
        "If `sym_sniff` returns no useful target, continue with native search and still call `sym_form_synapse` after "
        "the relevant files are known. Do not invent MCP results.\n"
    )
