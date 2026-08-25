import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from filelock import FileLock

SCHEMA_VERSION: str = "1.0"
MAX_RELATIONS_PER_FILE = 64
MAX_RELATION_WEIGHT = 100.0

@dataclass
class Synapse:
    """
    Represents a neural connection between a task intent and a specific file.
    
    Attributes:
        intent_hash: MD5 hash of the normalized user intent.
        target_filepath: Relative path to the file identified as the solution.
        weight: Strength of the connection, increases with successful use.
        last_accessed: Unix timestamp of the last time this synapse was triggered.
    """
    intent_hash: str
    target_filepath: str
    weight: float = 1.0
    last_accessed: float = field(default_factory=time.time)

class SymbioWorkspace:
    """
    Manages the local .symbio directory, acting as the 'cellular storage' for project-specific 
    intelligence including synapses, DNA rules, and scent maps.
    """
    def __init__(self, cwd: str = "."):
        self.root: Path = Path(cwd).resolve()
        self.symbio_dir: Path = self.root / ".symbio"
        self.synapse_file: Path = self.symbio_dir / "synapses.json"
        self.dna_file: Path = self.symbio_dir / "dna.json"
        self.scent_file: Path = self.symbio_dir / "scents.json"
        self.fingerprint_file: Path = self.symbio_dir / "fingerprints.json"
        self.mtime_file: Path = self.symbio_dir / "mtimes.json"
        self.skills_file: Path = self.symbio_dir / "skills.json"
        self.relations_file: Path = self.symbio_dir / "relations.json"
        self.lock_file: Path = self.symbio_dir / "workspace.lock"
        self.scan_lock_file: Path = self.symbio_dir / "scan.lock"
        self._memory_lock = threading.RLock()
        
        self.synapses: Dict[str, Synapse] = {}
        self.dna_rules: List[str] = []
        self.scent_map: Dict[str, List[str]] = {}
        self.fingerprints: Dict[str, Dict[str, Any]] = {}
        self.mtime_map: Dict[str, float] = {}
        self.skills: Dict[str, str] = {}
        self.relations: Dict[str, Dict[str, float]] = {} # source_file -> {target_file: weight}

    def is_initialized(self) -> bool:
        """Checks if the .symbio directory exists."""
        return self.symbio_dir.exists()

    def init_workspace(self) -> None:
        """Creates the .symbio directory and initializes empty state files."""
        self.symbio_dir.mkdir(exist_ok=True)
        self.save_state()

    def _apply_forgetting_curve(self) -> None:
        """
        Applies a time-based decay to synapse weights to simulate biological forgetting.
        Weak connections are pruned automatically.
        """
        current_time = time.time()
        for h, synapse in list(self.synapses.items()):
            days_passed = (current_time - synapse.last_accessed) / (24 * 3600)
            if days_passed > 0:
                synapse.weight *= (0.9 ** days_passed)
            if synapse.weight < 0.1:
                del self.synapses[h]

    def load_state(self) -> None:
        """Load the latest atomically published workspace sections."""
        if not self.is_initialized(): return
        
        with self._memory_lock:
            self._reload_sections_unlocked(self._section_names())

    def _load_json(self, path: Path, parser: Callable[[Any], Any], default: Any) -> Any:
        """Helper to safely load JSON files with custom parsing logic."""
        if not path.exists():
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return parser(json.load(f))
        except json.JSONDecodeError:
            print(
                f"🧬 [!] Corrupted genetic data detected ({path.name}). Call `sym_reindex` from MCP to repair.",
                file=sys.stderr,
            )
            return default
        except Exception as e:
            print(f"🧬 [!] Unknown biological mutation when loading {path.name}: {e}", file=sys.stderr)
            return default

    def save_state(self, sections: Optional[Iterable[str]] = None) -> None:
        """Atomically persists selected state sections under one workspace lock."""
        self.symbio_dir.mkdir(exist_ok=True)
        selected = self._section_names() if sections is None else list(dict.fromkeys(sections))
        unknown = set(selected) - set(self._section_names())
        if unknown:
            raise ValueError(f"unknown state sections: {', '.join(sorted(unknown))}")
        with self._memory_lock, FileLock(self.lock_file):
            self._save_sections_unlocked(selected)

    def _section_names(self) -> List[str]:
        return ["synapses", "dna", "scents", "fingerprints", "skills", "mtimes", "relations"]

    def _reload_sections_unlocked(self, sections: Iterable[str]) -> None:
        selected = set(sections)
        if "synapses" in selected:
            self.synapses = self._load_json(
                self.synapse_file,
                lambda data: {key: Synapse(**value) for key, value in data.items()},
                {},
            )
        if "dna" in selected:
            dna_data = self._load_json(self.dna_file, lambda data: data, {"rules": []})
            self.dna_rules = self._dedupe_preserve_order(dna_data.get("rules", []))
        if "scents" in selected:
            self.scent_map = self._load_json(self.scent_file, lambda data: data, {})
        if "fingerprints" in selected:
            self.fingerprints = self._load_json(self.fingerprint_file, lambda data: data, {})
        if "skills" in selected:
            self.skills = self._load_json(self.skills_file, lambda data: data, {})
        if "mtimes" in selected:
            self.mtime_map = self._load_json(self.mtime_file, lambda data: data, {})
        if "relations" in selected:
            self.relations = self._load_json(self.relations_file, lambda data: data, {})

    def _save_sections_unlocked(self, sections: Iterable[str]) -> None:
        payloads = {
            "synapses": (self.synapse_file, lambda: {key: value.__dict__ for key, value in self.synapses.items()}),
            "dna": (self.dna_file, lambda: {"version": SCHEMA_VERSION, "rules": self.dna_rules}),
            "scents": (self.scent_file, lambda: self.scent_map),
            "fingerprints": (self.fingerprint_file, lambda: self.fingerprints),
            "skills": (self.skills_file, lambda: self.skills),
            "mtimes": (self.mtime_file, lambda: self.mtime_map),
            "relations": (self.relations_file, lambda: self.relations),
        }
        try:
            for section in sections:
                path, payload_factory = payloads[section]
                self._atomic_write_json(path, payload_factory())
        except Exception as error:
            print(f"🧬 [!] Failed to persist genetic state: {error}", file=sys.stderr)
            raise

    def _mutate_sections(self, sections: Iterable[str], mutation: Callable[[], Any]) -> Any:
        selected = list(dict.fromkeys(sections))
        with self._memory_lock, FileLock(self.lock_file):
            self._reload_sections_unlocked(selected)
            changed, result = mutation()
            if changed:
                self._save_sections_unlocked(selected)
            return result

    def _atomic_write_json(self, path: Path, payload: Any) -> None:
        """Publish a complete JSON file without exposing a truncated intermediate."""
        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(path.parent),
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if temp_name and os.path.exists(temp_name):
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass

    def get_hash(self, text: str) -> str:
        """Generates a stable MD5 hash for a normalized string."""
        return hashlib.md5(text.strip().lower().encode('utf-8')).hexdigest()

    def get_antigen_key(self, text: str) -> str:
        """Builds a stable hash from intent vocabulary, allowing similar tasks to reuse memory."""
        words = self._intent_words(text)
        signature = " ".join(sorted(set(words)))
        return f"antigen:{self.get_hash(signature or text)}"

    def get_token_keys(self, text: str) -> List[str]:
        """Builds token-level memory keys for fuzzy intent recall."""
        return [f"token:{self.get_hash(word)}" for word in self._intent_words(text)]

    def get_o1_memory(self, task_intent: str) -> Optional[Synapse]:
        """Retrieve memory without mutating or persisting the full workspace."""
        with self._memory_lock:
            synapse = self.synapses.get(self.get_hash(task_intent)) or self.synapses.get(self.get_antigen_key(task_intent))
            if not synapse:
                token_hits = [self.synapses[key] for key in self.get_token_keys(task_intent) if key in self.synapses]
                if token_hits:
                    synapse = max(token_hits, key=self._effective_synapse_weight)
            if synapse and self._effective_synapse_weight(synapse) >= 0.1:
                return synapse
            return None

    def _effective_synapse_weight(self, synapse: Synapse, now: Optional[float] = None) -> float:
        elapsed_days = max(0.0, ((now or time.time()) - synapse.last_accessed) / (24 * 3600))
        return synapse.weight * (0.9 ** elapsed_days)

    def strengthen_synapse(self, task_intent: str, file_path: str, persist: bool = True) -> None:
        """Increases the weight of a neural connection after positive feedback."""
        if not persist:
            with self._memory_lock:
                self._strengthen_synapse_in_memory(task_intent, file_path)
            return
        self._mutate_sections(
            ["synapses"],
            lambda: (True, self._strengthen_synapse_in_memory(task_intent, file_path)),
        )

    def _strengthen_synapse_in_memory(self, task_intent: str, file_path: str) -> None:
        now = time.time()
        for h in {self.get_hash(task_intent), self.get_antigen_key(task_intent), *self.get_token_keys(task_intent)}:
            if h in self.synapses:
                self.synapses[h].weight += 1.5
                self.synapses[h].last_accessed = now
            else:
                self.synapses[h] = Synapse(h, file_path, weight=1.5, last_accessed=now)

    def record_feedback(self, task_intent: str, file_paths: List[str]) -> None:
        """Apply all feedback in memory and publish it with one save operation."""
        unique_paths = list(dict.fromkeys(file_paths))

        def mutate():
            for file_path in unique_paths:
                self._strengthen_synapse_in_memory(task_intent, file_path)
            for index, file_a in enumerate(unique_paths):
                for file_b in unique_paths[index + 1:]:
                    self._strengthen_relation_in_memory(file_a, file_b, weight=1.0)
            return True, None

        self._mutate_sections(["synapses", "relations"], mutate)

    def learn_skill(self, name: str, prompt_fragment: str) -> None:
        """Records a new 'code instinct' as a prompt fragment."""
        self._mutate_sections(
            ["skills"],
            lambda: (True, self.skills.__setitem__(name, prompt_fragment)),
        )

    def add_dna_rule(self, rule: str) -> bool:
        """Adds a DNA rule once. Returns True when a new rule was persisted."""
        normalized = rule.strip()

        def mutate():
            if not normalized or normalized in self.dna_rules:
                return False, False
            self.dna_rules.append(normalized)
            return True, True

        return self._mutate_sections(["dna"], mutate)

    def compact_rules(self) -> None:
        """Removes duplicated DNA rules accumulated by repeated negative feedback."""
        def mutate():
            compacted = self._dedupe_preserve_order(self.dna_rules)
            if compacted == self.dna_rules:
                return False, None
            self.dna_rules = compacted
            return True, None

        self._mutate_sections(["dna"], mutate)

    def strengthen_relation(self, file_a: str, file_b: str, weight: float = 1.0, persist: bool = True) -> None:
        """Strengthens the affinity between two files."""
        if not persist:
            with self._memory_lock:
                self._strengthen_relation_in_memory(file_a, file_b, weight)
            return
        self._mutate_sections(
            ["relations"],
            lambda: (True, self._strengthen_relation_in_memory(file_a, file_b, weight)),
        )

    def _strengthen_relation_in_memory(self, file_a: str, file_b: str, weight: float = 1.0) -> None:
        if file_a == file_b:
            return
        if file_a not in self.relations: self.relations[file_a] = {}
        if file_b not in self.relations: self.relations[file_b] = {}
        next_weight = min(MAX_RELATION_WEIGHT, self.relations[file_a].get(file_b, 0) + weight)
        self.relations[file_a][file_b] = next_weight
        self.relations[file_b][file_a] = next_weight
        self._trim_relations(file_a)
        self._trim_relations(file_b)

    def ensure_relation_weight(self, file_a: str, file_b: str, weight: float = 1.0) -> None:
        """Ensures a static affinity exists without inflating it on every reindex."""
        if file_a == file_b:
            return
        if file_a not in self.relations:
            self.relations[file_a] = {}
        if file_b not in self.relations:
            self.relations[file_b] = {}

        self.relations[file_a][file_b] = max(self.relations[file_a].get(file_b, 0), weight)
        self.relations[file_b][file_a] = max(self.relations[file_b].get(file_a, 0), weight)
        self._trim_relations(file_a)
        self._trim_relations(file_b)

    def _trim_relations(self, source: str) -> None:
        targets = self.relations.get(source, {})
        if len(targets) <= MAX_RELATIONS_PER_FILE:
            return
        keep = dict(sorted(targets.items(), key=lambda item: (-item[1], item[0]))[:MAX_RELATIONS_PER_FILE])
        removed = set(targets) - set(keep)
        self.relations[source] = keep
        for target in removed:
            reverse = self.relations.get(target)
            if reverse is not None:
                reverse.pop(source, None)
                if not reverse:
                    self.relations.pop(target, None)

    def compact_relations(self) -> None:
        """Enforce the graph degree bound during explicit/background index work."""
        for source in list(self.relations):
            self._trim_relations(source)

    def publish_index_state(
        self,
        scent_map: Dict[str, List[str]],
        fingerprints: Dict[str, Dict[str, Any]],
        mtime_map: Dict[str, Any],
        relations: Dict[str, Dict[str, float]],
    ) -> None:
        with self._memory_lock, FileLock(self.lock_file):
            self._reload_sections_unlocked(["relations"])
            valid_sources = {
                source
                for source in self.relations
                if (self.root / source).is_file()
            }
            self.relations = {
                source: {
                    target: weight
                    for target, weight in targets.items()
                    if target in valid_sources and (self.root / target).is_file()
                }
                for source, targets in self.relations.items()
                if source in valid_sources
            }
            self.relations = {
                source: targets
                for source, targets in self.relations.items()
                if targets
            }
            for source, targets in relations.items():
                current = self.relations.setdefault(source, {})
                for target, weight in targets.items():
                    current[target] = max(current.get(target, 0.0), weight)
            self.scent_map = scent_map
            self.fingerprints = fingerprints
            self.mtime_map = mtime_map
            self.compact_relations()
            self._save_sections_unlocked(["scents", "fingerprints", "mtimes", "relations"])

    def weaken_and_mutate(self, task_intent: str, rule: str) -> None:
        """Prunes a wrong neural connection and adds a restrictive DNA rule."""
        def mutate():
            for key in {self.get_hash(task_intent), self.get_antigen_key(task_intent), *self.get_token_keys(task_intent)}:
                self.synapses.pop(key, None)
            normalized = rule.strip()
            if normalized and normalized not in self.dna_rules:
                self.dna_rules.append(normalized)
            return True, None

        self._mutate_sections(["synapses", "dna"], mutate)

    def _dedupe_preserve_order(self, items: List[str]) -> List[str]:
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def _intent_words(self, text: str) -> List[str]:
        stop_words = {"add", "fix", "the", "and", "for", "with", "into", "from", "this", "that"}
        words = []
        for word in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split():
            if re.search(r"[\u3400-\u9fff]", word):
                words.extend(word[index:index + 2] for index in range(len(word) - 1))
                words.extend(word[index:index + 3] for index in range(len(word) - 2))
            elif len(word) > 2 and word not in stop_words:
                words.append(word)
        return list(dict.fromkeys(words))
