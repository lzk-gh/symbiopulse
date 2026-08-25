"""Bounded, deterministic project indexing primitives."""

from .path_filter import PathFilter, ScanBudgetExceeded
from .terms import MAX_POSTINGS_PER_TERM, MAX_QUERY_CANDIDATES, search_terms

__all__ = [
    "MAX_POSTINGS_PER_TERM",
    "MAX_QUERY_CANDIDATES",
    "PathFilter",
    "ScanBudgetExceeded",
    "search_terms",
]
