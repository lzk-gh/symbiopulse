import json
import re
import hashlib
import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Callable
from ..core.config import SymbioConfig
from ..indexing.path_filter import PathFilter, ScanBudgetExceeded
from ..indexing.terms import MAX_POSTINGS_PER_TERM, search_terms

try:
    import litellm
except ImportError:
    litellm = None

class OlfactoryEngine:
    """
    Biological sniffing engine that scans the project to build a 'scent map'.
    Uses industrial-grade ignore logic and LLM-powered semantic fingerprinting.
    """
    def __init__(self, root_dir: str = "."):
        self.root = Path(root_dir).resolve()
        self.path_filter = PathFilter(str(self.root))
        self.default_ignores = list(PathFilter.DEFAULT_IGNORES)
        self.scent_map: Dict[str, List[str]] = {}
        self.fingerprint_map: Dict[str, Dict[str, Any]] = {}
        self.mtime_map: Dict[str, float] = {}
        
        # Regex for import extraction
        self.import_patterns = {
            ".py": re.compile(r'^(?:from\s+([.\w]+)\s+import|import\s+([.\w]+))', re.MULTILINE),
            ".js": re.compile(r'(?:import\s+.*?from\s+[\'"](.*?)[\'"]|require\([\'"](.*?)[\'"]\))', re.MULTILINE),
            ".ts": re.compile(r'(?:import\s+.*?from\s+[\'"](.*?)[\'"]|require\([\'"](.*?)[\'"]\))', re.MULTILINE)
        }
        
        # Regex for feature fingerprinting (functions/classes)
        self.feature_patterns = {
            ".py": re.compile(r'^(?:class|def)\s+([a-zA-Z_]\w*)', re.MULTILINE),
            ".js": re.compile(r'(?:class|function|const|let|var)\s+([a-zA-Z_]\w*)\s*(?:=|extends|\()', re.MULTILINE),
            ".ts": re.compile(r'(?:class|interface|type|function|const|let|var)\s+([a-zA-Z_]\w*)\s*(?:=|extends|implements|\<|\()', re.MULTILINE)
        }

    def is_ignored(self, path: str) -> bool:
        """Use the canonical scanner policy for ignore and filesystem boundaries."""
        return self.path_filter.is_ignored(path)

    def _extract_file_intelligence(self, file_path: Path, max_bytes: int) -> Tuple[List[str], List[str]]:
        """Extracts imports (for affinity) and structure features (for scents)."""
        imports: List[str] = []
        features: List[str] = []
        ext = file_path.suffix
        
        if ext not in self.import_patterns:
            return imports, features
            
        try:
            if file_path.stat().st_size > max_bytes:
                return imports, features
            with file_path.open("rb") as handle:
                content = handle.read(max_bytes).decode("utf-8", errors="ignore")
            
            # Extract imports
            for match in self.import_patterns[ext].finditer(content):
                imp = match.group(1) or match.group(2)
                if imp: imports.append(imp)
                
            # Extract features
            for match in self.feature_patterns[ext].finditer(content):
                feat = match.group(1)
                if feat and len(feat) > 2: features.append(feat.lower())
                
        except Exception:
            pass
            
        return imports, features

    def _build_directory_fingerprint(
        self,
        rel_path: str,
        files: List[str],
        features: List[str],
        deadline: Optional[float] = None,
        max_seconds: float = 0.0,
    ) -> Dict[str, Any]:
        """Builds a deterministic directory snowflake for MCP-time context assembly."""
        extensions: Dict[str, int] = {}
        sorted_files = sorted(files)
        file_index: Dict[str, List[int]] = {}
        for index, name in enumerate(sorted_files):
            if deadline is not None and index % 256 == 0 and time.monotonic() > deadline:
                raise ScanBudgetExceeded(f"scan exceeded {max_seconds:.1f}s time budget")
            suffix = Path(name).suffix.lower() or "<none>"
            extensions[suffix] = extensions.get(suffix, 0) + 1
            for term in search_terms(name):
                postings = file_index.setdefault(term, [])
                if len(postings) < MAX_POSTINGS_PER_TERM:
                    postings.append(index)

        keywords = self._fallback_keywords(rel_path, sorted_files[:512], features)
        payload = json.dumps(
            {
                "path": rel_path,
                "files": sorted_files,
                "features": sorted(set(features)),
                "extensions": extensions,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        return {
            "path": rel_path,
            "files": sorted_files,
            "file_index": file_index,
            "file_count": len(files),
            "extensions": extensions,
            "symbols": sorted(set(features))[:40],
            "keywords": keywords,
            "fingerprint": hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16],
        }

    def _fallback_keywords(self, rel_path: str, files: List[str], features: List[str]) -> List[str]:
        words: List[str] = []
        for item in [rel_path, *files, *features]:
            cleaned = re.sub(r"[^a-zA-Z0-9_]+", " ", item).lower()
            words.extend(part for part in cleaned.split() if len(part) > 2)
        return sorted(set(words))[:12]

    def _directory_signature(
        self,
        root: Path,
        files: List[str],
        deadline: float,
        max_seconds: float,
    ) -> str:
        digest = hashlib.sha256()
        for name in files:
            if time.monotonic() > deadline:
                raise ScanBudgetExceeded(f"scan exceeded {max_seconds:.1f}s time budget")
            path = root / name
            try:
                stat_result = path.stat()
                digest.update(f"{name}\0{stat_result.st_size}\0{stat_result.st_mtime_ns}\n".encode("utf-8"))
            except OSError:
                digest.update(f"{name}\0missing\n".encode("utf-8"))
        return digest.hexdigest()

    def scan(self, 
             previous_scent_map: Optional[Dict[str, List[str]]] = None, 
             previous_mtime_map: Optional[Dict[str, float]] = None, 
             progress_callback: Optional[Callable[[int, int, str], None]] = None, 
             mode: str = "standard", 
             workspace: Any = None) -> Tuple[Dict[str, List[str]], Dict[str, float]]:
        """
        Builds a map of directory -> semantic keywords using LLM, and extracts static affinity.
        Only rescans directories that have changed since the last run.
        """
        cfg = SymbioConfig(str(self.root))
        max_seconds = float(cfg.get("scan_max_seconds"))
        deadline = time.monotonic() + max_seconds
        max_file_bytes = int(cfg.get("scan_max_file_bytes"))
        semantic_requests = 0
        
        new_map = previous_scent_map.copy() if previous_scent_map else {}
        new_fingerprints: Dict[str, Dict[str, Any]] = getattr(workspace, "fingerprints", {}).copy() if workspace else {}
        self.mtime_map = previous_mtime_map.copy() if previous_mtime_map else {}
        
        observed_dirs = set()
        directory_iterator = self.path_filter.walk(
            max_directories=int(cfg.get("scan_max_directories")),
            max_files=int(cfg.get("scan_max_files")),
            max_seconds=max_seconds,
            deadline=deadline,
        )
        for i, (root, rel_path, files) in enumerate(directory_iterator):
            observed_dirs.add(rel_path)
            if progress_callback:
                progress_callback(i, 0, rel_path)

            directory_signature = self._directory_signature(Path(root), files, deadline, max_seconds)
            
            unchanged = (
                mode != "full"
                and rel_path in self.mtime_map
                and self.mtime_map[rel_path] == directory_signature
                and rel_path in new_map
                and rel_path in new_fingerprints
            )
            if unchanged:
                continue

            # Static affinity & feature extraction
            dir_features: List[str] = []
            visible_files = files
            for f in files:
                if time.monotonic() > deadline:
                    raise ScanBudgetExceeded(f"scan exceeded {max_seconds:.1f}s time budget")
                f_path = Path(root) / f
                if f_path.is_file() and not self.is_ignored(str(f_path)):
                    imports, features = self._extract_file_intelligence(f_path, max_file_bytes)
                    dir_features.extend(features)
                    # Add static affinity to workspace if provided
                    if workspace and imports:
                        f_rel = str(f_path.relative_to(self.root)).replace("\\", "/")
                        for imp in imports:
                            # Heuristic matching: find if 'imp' exists in files
                            imp_name = imp.split(".")[-1] if "." in imp else imp.split("/")[-1]
                            for other_f in files:
                                if imp_name in other_f and f != other_f:
                                    other_rel = str((Path(root) / other_f).relative_to(self.root)).replace("\\", "/")
                                    workspace.ensure_relation_weight(f_rel, other_rel, weight=0.5)

            fingerprint = self._build_directory_fingerprint(
                rel_path,
                visible_files,
                dir_features,
                deadline=deadline,
                max_seconds=max_seconds,
            )
            new_fingerprints[rel_path] = fingerprint

            self.mtime_map[rel_path] = directory_signature
            
            # Extract high-level semantics using LLM
            file_list = ", ".join(visible_files[:10])
            feature_list = ", ".join(list(set(dir_features))[:15])
            prompt = (
                f"Directory: {rel_path}\n"
                f"Files: {file_list}\n"
                f"Key Symbols: {feature_list}\n"
                f"Generate 5-8 semantic keywords (in English) for this directory. "
                f"Return as a comma-separated list."
            )
            
            try:
                if litellm is None or not self._semantic_scan_enabled(cfg):
                    raise RuntimeError("semantic scan is not configured")
                if semantic_requests >= int(cfg.get("semantic_max_requests")):
                    raise RuntimeError("semantic request budget exhausted")
                semantic_requests += 1
                response = litellm.completion(
                    model=cfg.get("model"),
                    messages=[{"role": "user", "content": prompt}],
                    api_base=cfg.get("api_base"),
                    timeout=float(cfg.get("semantic_timeout_seconds")),
                )
                keywords = [k.strip().lower() for k in response.choices[0].message.content.split(",")]
            except Exception:
                # Fallback to feature-based keywords if LLM fails
                keywords = fingerprint["keywords"]
            
            if keywords:
                new_map[rel_path] = list(set(keywords))
            if time.monotonic() > deadline:
                raise ScanBudgetExceeded(f"scan exceeded {max_seconds:.1f}s time budget")

        for stale_zone in set(new_map) - observed_dirs:
            new_map.pop(stale_zone, None)
            self.mtime_map.pop(stale_zone, None)
        for stale_zone in set(new_fingerprints) - observed_dirs:
            new_fingerprints.pop(stale_zone, None)
        
        self.scent_map = new_map
        self.fingerprint_map = new_fingerprints
        if workspace is not None:
            workspace.fingerprints = new_fingerprints
        return new_map, self.mtime_map

    def _semantic_scan_enabled(self, cfg: SymbioConfig) -> bool:
        """Semantic enrichment is explicit opt-in; ambient keys never enable it."""
        return cfg.get("semantic_enabled") is True

    def sniff_target_zones(self, user_intent: str) -> List[str]:
        """Identifies relevant directories by matching user intent against the scent map."""
        zones: List[str] = []
        intent_lower = user_intent.lower()
        for zone, keywords in self.scent_map.items():
            zone_parts = zone.lower().split("/")
            # Match against directory path parts
            if any(part in intent_lower for part in zone_parts if len(part) > 2):
                zones.append(zone)
                continue
            # Match against semantic keywords
            hit_count = sum(1 for kw in keywords if kw in intent_lower)
            if hit_count > 0:
                zones.append(zone)
        return zones
