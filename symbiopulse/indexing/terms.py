import re
from typing import Set


MAX_POSTINGS_PER_TERM = 512
MAX_QUERY_CANDIDATES = 4096


def search_terms(text: str) -> Set[str]:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).replace("_", " ")
    terms = {
        term.lower()
        for term in re.findall(r"[\w]+", normalized, flags=re.UNICODE)
        if len(term) > 1
    }
    for sequence in re.findall(r"[\u3400-\u9fff]{2,}", normalized):
        terms.update(sequence[index:index + 2] for index in range(len(sequence) - 1))
        terms.update(sequence[index:index + 3] for index in range(len(sequence) - 2))
    return terms
