import json
import hashlib
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from filelock import FileLock

SCHEMA_VERSION: str = "1.0"

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
        self.symbio_dir: Path = Path(cwd) / ".symbio"
        self.synapse_file: Path = self.symbio_dir / "synapses.json"
        self.dna_file: Path = self.symbio_dir / "dna.json"
        self.scent_file: Path = self.symbio_dir / "scents.json"
        self.fingerprint_file: Path = self.symbio_dir / "fingerprints.json"
        self.mtime_file: Path = self.symbio_dir / "mtimes.json"
        self.skills_file: Path = self.symbio_dir / "skills.json"
        self.relations_file: Path = self.symbio_dir / "relations.json"
        self.lock_file: Path = self.symbio_dir / "workspace.lock"
        
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

        # Apply slight decay to file relations as well
        for source, targets in list(self.relations.items()):
            for target, weight in list(targets.items()):
                # very slow decay for relations
                new_weight = weight * 0.99 
                if new_weight < 0.1:
                    del targets[target]
                else:
                    targets[target] = new_weight
            if not targets:
                del self.relations[source]

    def load_state(self) -> None:
        """
        Loads the project's biological state from the .symbio directory.
        Uses file locking to ensure data integrity during concurrent access.
        """
        if not self.is_initialized(): return
        
        lock = FileLock(self.lock_file)
        with lock:
            self.synapses = self._load_json(self.synapse_file, lambda d: {k: Synapse(**v) for k, v in d.items()}, {})
            dna_data = self._load_json(self.dna_file, lambda d: d, {"rules": []})
            self.dna_rules = self._dedupe_preserve_order(dna_data.get("rules", []))
            self.scent_map = self._load_json(self.scent_file, lambda d: d, {})
            self.fingerprints = self._load_json(self.fingerprint_file, lambda d: d, {})
            self.skills = self._load_json(self.skills_file, lambda d: d, {})
            self.mtime_map = self._load_json(self.mtime_file, lambda d: d, {})
            self.relations = self._load_json(self.relations_file, lambda d: d, {})

    def _load_json(self, path: Path, parser: Callable[[Any], Any], default: Any) -> Any:
        """Helper to safely load JSON files with custom parsing logic."""
        if not path.exists():
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return parser(json.load(f))
        except json.JSONDecodeError:
            print(f"🧬 [!] Corrupted genetic data detected ({path.name}). Call `sym_reindex` from MCP to repair.")
            return default
        except Exception as e:
            print(f"🧬 [!] Unknown biological mutation when loading {path.name}: {e}")
            return default

    def save_state(self) -> None:
        """Persists the current state to the .symbio directory using file locks."""
        self.symbio_dir.mkdir(exist_ok=True)
        lock = FileLock(self.lock_file)
        with lock:
            try:
                with open(self.synapse_file, "w", encoding="utf-8") as f:
                    json.dump({k: v.__dict__ for k, v in self.synapses.items()}, f, ensure_ascii=False, indent=2)
                with open(self.dna_file, "w", encoding="utf-8") as f:
                    json.dump({"version": SCHEMA_VERSION, "rules": self.dna_rules}, f, ensure_ascii=False, indent=2)
                with open(self.scent_file, "w", encoding="utf-8") as f:
                    json.dump(self.scent_map, f, ensure_ascii=False, indent=2)
                with open(self.fingerprint_file, "w", encoding="utf-8") as f:
                    json.dump(self.fingerprints, f, ensure_ascii=False, indent=2)
                with open(self.skills_file, "w", encoding="utf-8") as f:
                    json.dump(self.skills, f, ensure_ascii=False, indent=2)
                with open(self.mtime_file, "w", encoding="utf-8") as f:
                    json.dump(self.mtime_map, f, ensure_ascii=False, indent=2)
                with open(self.relations_file, "w", encoding="utf-8") as f:
                    json.dump(self.relations, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"🧬 [!] Failed to persist genetic state: {e}")

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
        """Retrieves an O(1) memory reflex for a given intent, if it exists."""
        self._apply_forgetting_curve()
        synapse = self.synapses.get(self.get_hash(task_intent)) or self.synapses.get(self.get_antigen_key(task_intent))
        if not synapse:
            token_hits = [self.synapses[key] for key in self.get_token_keys(task_intent) if key in self.synapses]
            if token_hits:
                synapse = max(token_hits, key=lambda item: item.weight)
        if synapse:
            synapse.last_accessed = time.time()
            self.save_state()
        return synapse

    def strengthen_synapse(self, task_intent: str, file_path: str) -> None:
        """Increases the weight of a neural connection after positive feedback."""
        for h in {self.get_hash(task_intent), self.get_antigen_key(task_intent), *self.get_token_keys(task_intent)}:
            if h in self.synapses:
                self.synapses[h].weight += 1.5
                self.synapses[h].last_accessed = time.time()
            else:
                self.synapses[h] = Synapse(h, file_path, weight=1.5, last_accessed=time.time())
        self.save_state()

    def learn_skill(self, name: str, prompt_fragment: str) -> None:
        """Records a new 'code instinct' as a prompt fragment."""
        self.skills[name] = prompt_fragment
        self.save_state()

    def add_dna_rule(self, rule: str) -> bool:
        """Adds a DNA rule once. Returns True when a new rule was persisted."""
        normalized = rule.strip()
        if not normalized:
            return False
        if normalized in self.dna_rules:
            return False
        self.dna_rules.append(normalized)
        self.save_state()
        return True

    def compact_rules(self) -> None:
        """Removes duplicated DNA rules accumulated by repeated negative feedback."""
        compacted = self._dedupe_preserve_order(self.dna_rules)
        if compacted != self.dna_rules:
            self.dna_rules = compacted
            self.save_state()

    def strengthen_relation(self, file_a: str, file_b: str, weight: float = 1.0) -> None:
        """Strengthens the affinity between two files."""
        if file_a == file_b: return
        if file_a not in self.relations: self.relations[file_a] = {}
        if file_b not in self.relations: self.relations[file_b] = {}
        
        self.relations[file_a][file_b] = self.relations[file_a].get(file_b, 0) + weight
        self.relations[file_b][file_a] = self.relations[file_b].get(file_a, 0) + weight
        self.save_state()

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

    def weaken_and_mutate(self, task_intent: str, rule: str) -> None:
        """Prunes a wrong neural connection and adds a restrictive DNA rule."""
        for h in {self.get_hash(task_intent), self.get_antigen_key(task_intent), *self.get_token_keys(task_intent)}:
            if h in self.synapses:
                del self.synapses[h]
        self.add_dna_rule(rule)
        self.save_state()

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
        return [
            w for w in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
            if len(w) > 2 and w not in stop_words
        ]
