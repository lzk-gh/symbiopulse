import os
import json
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Callable
from ..core.config import SymbioConfig

try:
    import pathspec
except ImportError:
    pathspec = None

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
        self.root = Path(root_dir)
        # Default internal hardcoded ignores
        self.default_ignores = [
            ".git/", "node_modules/", "__pycache__/", ".symbio/", 
            "venv/", ".venv/", "dist/", "build/", "*.pyc", ".DS_Store",
            ".cursor/", ".github/", ".idea/", ".vscode/", ".pytest_cache/", ".mypy_cache/",
            ".ruff_cache/", ".next/", "coverage/", "htmlcov/", "target/"
        ]
        self.ignored_dir_names = {
            pattern.strip("/")
            for pattern in self.default_ignores
            if pattern.endswith("/") and "*" not in pattern
        }
        self.scent_map: Dict[str, List[str]] = {}
        self.fingerprint_map: Dict[str, Dict[str, Any]] = {}
        self.mtime_map: Dict[str, float] = {}
        self._init_spec()
        
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

    def _init_spec(self) -> None:
        """Builds a unified pathspec from default, .gitignore, and .symbioignore."""
        patterns = self.default_ignores.copy()
        
        # Load .gitignore
        gitignore = self.root / ".gitignore"
        if gitignore.exists():
            patterns.extend(gitignore.read_text(encoding="utf-8").splitlines())
            
        # Load .symbioignore (Highest priority)
        symignore = self.root / ".symbioignore"
        if symignore.exists():
            patterns.extend(symignore.read_text(encoding="utf-8").splitlines())
            
        self.ignore_patterns = [p.strip() for p in patterns if p.strip() and not p.strip().startswith("#")]
        self.spec = pathspec.PathSpec.from_lines('gitignore', self.ignore_patterns) if pathspec else None

    def is_ignored(self, path: str) -> bool:
        """Checks if a path (relative to root) is ignored by looking at pathspec."""
        try:
            rel_path = os.path.relpath(path, self.root).replace("\\", "/")
            if rel_path == ".": return False
            if any(part in self.ignored_dir_names for part in rel_path.split("/")):
                return True
            if self.spec:
                return self.spec.match_file(rel_path)
            return self._fallback_ignore_match(rel_path)
        except Exception:
            return False

    def _fallback_ignore_match(self, rel_path: str) -> bool:
        """Small gitignore subset used when pathspec is unavailable."""
        parts = rel_path.split("/")
        for pattern in self.ignore_patterns:
            normalized = pattern.strip("/")
            if not normalized:
                continue
            if pattern.endswith("/") and normalized in parts:
                return True
            if pattern.startswith("*.") and rel_path.endswith(pattern[1:]):
                return True
            if normalized == rel_path or normalized in parts:
                return True
        return False

    def _extract_file_intelligence(self, file_path: Path) -> Tuple[List[str], List[str]]:
        """Extracts imports (for affinity) and structure features (for scents)."""
        imports: List[str] = []
        features: List[str] = []
        ext = file_path.suffix
        
        if ext not in self.import_patterns:
            return imports, features
            
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            
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

    def _build_directory_fingerprint(self, rel_path: str, files: List[str], features: List[str]) -> Dict[str, Any]:
        """Builds a deterministic directory snowflake for MCP-time context assembly."""
        extensions: Dict[str, int] = {}
        for name in files:
            suffix = Path(name).suffix.lower() or "<none>"
            extensions[suffix] = extensions.get(suffix, 0) + 1

        keywords = self._fallback_keywords(rel_path, files, features)
        payload = json.dumps(
            {
                "path": rel_path,
                "files": sorted(files),
                "features": sorted(set(features)),
                "extensions": extensions,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        return {
            "path": rel_path,
            "files": sorted(files)[:30],
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
        cfg = SymbioConfig()
        
        new_map = previous_scent_map.copy() if previous_scent_map else {}
        new_fingerprints: Dict[str, Dict[str, Any]] = getattr(workspace, "fingerprints", {}).copy() if workspace else {}
        self.mtime_map = previous_mtime_map.copy() if previous_mtime_map else {}
        
        all_dirs = []
        for root, dirs, files in os.walk(self.root):
            # IN-PLACE PRUNING: This is the critical fix for efficiency
            # We must modify 'dirs' to prevent os.walk from entering ignored folders
            dirs[:] = [d for d in dirs if not self.is_ignored(os.path.join(root, d))]
            
            rel_path = os.path.relpath(root, self.root).replace("\\", "/")
            if rel_path == "." or self.is_ignored(root):
                continue
                
            all_dirs.append((root, rel_path, files))

        observed_dirs = {rel_path for _, rel_path, _ in all_dirs}
        for stale_zone in set(new_map) - observed_dirs:
            new_map.pop(stale_zone, None)
        for stale_zone in set(new_fingerprints) - observed_dirs:
            new_fingerprints.pop(stale_zone, None)

        total_dirs = len(all_dirs)
        for i, (root, rel_path, files) in enumerate(all_dirs):
            if progress_callback:
                progress_callback(i, total_dirs, rel_path)

            try:
                dir_mtime = os.path.getmtime(root)
            except Exception:
                dir_mtime = 0
            
            # Static affinity & feature extraction
            dir_features: List[str] = []
            visible_files = [f for f in files if not self.is_ignored(os.path.join(root, f))]
            for f in files:
                f_path = Path(root) / f
                if f_path.is_file() and not self.is_ignored(str(f_path)):
                    imports, features = self._extract_file_intelligence(f_path)
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

            fingerprint = self._build_directory_fingerprint(rel_path, visible_files, dir_features)
            new_fingerprints[rel_path] = fingerprint

            # Skip LLM tagging if mtime hasn't changed and keywords already exist
            if rel_path in self.mtime_map and self.mtime_map[rel_path] >= dir_mtime and rel_path in new_map:
                continue 
                
            self.mtime_map[rel_path] = dir_mtime
            
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
                response = litellm.completion(
                    model=cfg.get("model"),
                    messages=[{"role": "user", "content": prompt}],
                    api_base=cfg.get("api_base")
                )
                keywords = [k.strip().lower() for k in response.choices[0].message.content.split(",")]
            except Exception:
                # Fallback to feature-based keywords if LLM fails
                keywords = fingerprint["keywords"]
            
            if keywords:
                new_map[rel_path] = list(set(keywords))
        
        self.scent_map = new_map
        self.fingerprint_map = new_fingerprints
        if workspace is not None:
            workspace.fingerprints = new_fingerprints
        return new_map, self.mtime_map

    def _semantic_scan_enabled(self, cfg: SymbioConfig) -> bool:
        """Avoid noisy LLM failures during zero-config MCP startup."""
        if cfg.get("api_base"):
            return True
        return any(
            os.environ.get(name)
            for name in [
                "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY",
                "DEEPSEEK_API_KEY",
                "GEMINI_API_KEY",
                "LITELLM_API_KEY",
            ]
        )

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
