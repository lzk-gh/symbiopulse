from pathlib import Path
from typing import List, Dict, Tuple, Optional
from difflib import SequenceMatcher

from ..indexing.terms import MAX_QUERY_CANDIDATES, search_terms

class ResonatorEngine:
    """
    Calculates resonance by reading actual files in targeted zones.
    Uses structural and semantic matching to identify the best candidates.
    """
    def __init__(self, root_dir: str = "."):
        self.root = Path(root_dir)

    def trigger_resonance(self, intent: str, zones: List[str]) -> Optional[str]:
        """Returns the single best match (Legacy interface)."""
        matches = self.trigger_resonance_multi(intent, zones, top_n=1)
        return matches[0] if matches else None

    def trigger_resonance_multi(
        self,
        intent: str,
        zones: List[str],
        top_n: int = 3,
        fingerprints: Optional[Dict[str, Dict]] = None,
    ) -> List[str]:
        """Returns top N matching files based on resonance score."""
        if fingerprints is not None:
            return self._rank_snapshot(intent, zones, fingerprints, top_n)

        scores: List[Tuple[str, float]] = []
        intent_lower = intent.lower()

        for zone in zones:
            zone_path = self.root / zone
            if not zone_path.exists(): continue
            
            for f in zone_path.iterdir():
                if f.is_file():
                    try:
                        # Read first 1000 chars for a "structural vibe" check
                        content = f.read_text(encoding="utf-8", errors="ignore")[:1000]
                        
                        # Score based on filename and content snippet
                        score = SequenceMatcher(None, intent_lower, f.name.lower()).ratio() * 0.7
                        score += SequenceMatcher(None, intent_lower, content.lower()).ratio() * 0.3
                        
                        # --- ARCHITECTURAL GRAVITY ---
                        rel_path = str(f.relative_to(self.root)).replace("\\", "/")
                        # Boost scores for non-test, non-doc directories
                        if "test" in rel_path.lower() or "doc" in rel_path.lower():
                            score *= 0.5
                        elif any(core in rel_path.lower() for core in ["core", "src", "engine", "service"]):
                            score *= 1.5 # Significant boost for core logic
                        
                        if score > 0.1: # Only keep meaningful matches
                            scores.append((rel_path, score))
                    except Exception:
                        continue
                        
        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        return [path for path, score in scores[:top_n]]

    def _rank_snapshot(
        self,
        intent: str,
        zones: List[str],
        fingerprints: Dict[str, Dict],
        top_n: int,
    ) -> List[str]:
        """Rank bounded fingerprint candidates without opening project files."""
        intent_terms = search_terms(intent)
        scores: Dict[str, float] = {}
        for zone in zones[:12]:
            fingerprint = fingerprints.get(zone, {})
            zone_terms = search_terms(
                " ".join(
                    [
                        zone,
                        *fingerprint.get("keywords", []),
                        *fingerprint.get("symbols", []),
                    ]
                )
            )
            zone_score = len(intent_terms & zone_terms) * 0.25
            files = fingerprint.get("files", [])
            file_index = fingerprint.get("file_index")
            if isinstance(file_index, dict):
                postings = [file_index[term] for term in intent_terms if term in file_index]
                candidate_indices = set()
                for posting in sorted(postings, key=len):
                    for index in posting:
                        if isinstance(index, int) and 0 <= index < len(files):
                            candidate_indices.add(index)
                            if len(candidate_indices) >= MAX_QUERY_CANDIDATES:
                                break
                    if len(candidate_indices) >= MAX_QUERY_CANDIDATES:
                        break
            else:
                candidate_indices = range(min(len(files), MAX_QUERY_CANDIDATES))

            for index in candidate_indices:
                filename = files[index]
                relative = (Path(zone) / filename).as_posix()
                file_terms = search_terms(relative)
                overlap = len(intent_terms & file_terms)
                if overlap == 0:
                    continue
                score = overlap * 1.5 + zone_score
                if Path(filename).stem.lower() in intent.lower():
                    score += 2.0
                scores[relative] = max(scores.get(relative, 0.0), score)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [path for path, _ in ranked[:top_n]]

    def expand_context(self, 
                       primary_file: str, 
                       relations: Dict[str, Dict[str, float]], 
                       max_depth: int = 2, 
                       top_n: int = 5) -> List[str]:
        """
        Expands context based on synaptic relations using a gravity-based scoring logic.
        Score = (Relevance * Weight) / (Distance^2 + 1)
        """
        context_scores: Dict[str, float] = {} # file -> score
        # queue item: (file, depth, relevance)
        # Primary file starts at depth 0, relevance 1.0
        queue: List[Tuple[str, int, float]] = [(primary_file, 0, 1.0)] 
        visited = {primary_file}
        
        while queue:
            current, depth, relevance = queue.pop(0)
            if depth >= max_depth: continue
            
            if current in relations:
                for related_file, weight in relations[current].items():
                    if related_file == primary_file: continue
                    
                    distance = depth + 1
                    # Professional scoring math: Score = (Relevance * Weight) / (Distance^2 + 1)
                    score = (relevance * weight) / (distance ** 2 + 1)
                    
                    # Update score if higher
                    if related_file not in context_scores or score > context_scores[related_file]:
                        context_scores[related_file] = score
                        
                        if related_file not in visited:
                            visited.add(related_file)
                            # Enqueue for further traversal with relevance decay
                            queue.append((related_file, depth + 1, relevance * 0.8))
                        
        # Sort by score descending and take top N
        sorted_files = sorted(context_scores.items(), key=lambda x: x[1], reverse=True)
        return [path for path, score in sorted_files[:top_n]]
