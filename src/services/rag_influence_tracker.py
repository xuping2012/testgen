import re
from typing import Dict, List, Any, Optional


def check_rag_match(case_text: str, source_text: str) -> int:
    chinese_words = re.findall(r"[\u4e00-\u9fff]{2,}", source_text)
    for word in chinese_words:
        for i in range(len(word) - 1):
            for length in range(2, len(word) + 1):
                if i + length <= len(word):
                    substring = word[i : i + length]
                    if substring in case_text:
                        return 1
    english_words = re.findall(r"[a-zA-Z]{2,}", source_text.lower())
    for word in english_words:
        if word.lower() in case_text.lower():
            return 1
    return 0


def calc_case_rag_influence(
    case: Dict[str, Any],
    rag_sources: List[Dict[str, Any]],
    threshold: float = 0.1,
) -> Dict[str, Any]:
    case_text = f"{case.get('name', '')} {case.get('test_point', '')} {' '.join(case.get('test_steps', []))}"
    matched_sources = []

    for source in rag_sources:
        source_text = source.get("content", "")
        if check_rag_match(case_text, source_text):
            matched_sources.append(
                {
                    "type": source.get("type", "case"),
                    "id": source.get("id", ""),
                    "similarity": 1.0,
                }
            )

    return {
        "influenced": len(matched_sources) > 0,
        "similarity": 1.0 if matched_sources else 0.0,
        "sources": matched_sources,
    }


def calc_rag_influence(
    cases: List[Dict[str, Any]],
    rag_sources: List[Dict[str, Any]],
    threshold: float = 0.1,
) -> List[Dict[str, Any]]:
    if not rag_sources:
        for case in cases:
            case["rag_influenced"] = 0
            case["rag_sources"] = []
        return cases

    results = []
    for case in cases:
        result = calc_case_rag_influence(case, rag_sources, threshold)
        case["rag_influenced"] = 1 if result["influenced"] else 0
        case["rag_sources"] = result["sources"]
        results.append(case)

    return results
