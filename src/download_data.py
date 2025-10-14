from datasets import load_dataset
import random
import json
from collections import Counter, defaultdict
import argparse
from pathlib import Path

SEED = 12345

def _normalize(name: str) -> str:
    return name.lower().replace(" ", "").replace("_", "") if isinstance(name, str) else name

def _find_column(ds, logical_name: str, fallback_variants=None) -> str:
    """Find a column by tolerant name matching (case/space/underscore-insensitive)."""
    fallback_variants = fallback_variants or []
    norm_map = {_normalize(n): n for n in ds.column_names}
    targets = [_normalize(logical_name)] + [_normalize(v) for v in fallback_variants]
    for t in targets:
        if t in norm_map:
            return norm_map[t]
    raise KeyError(f"Couldn't find a '{logical_name}' column. Available columns: {ds.column_names}")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sample MedCalc dataset with a per-question limit.")
    parser.add_argument("--per-question", "-k", type=int, default=2,
                        help="Number of examples to pull per unique question (default: 2).")
    args = parser.parse_args()
    if args.per_question < 1:
        raise ValueError("--per-question must be >= 1")
    return args

if __name__ == "__main__":
    args = parse_args()
    PER_QUESTION = args.per_question
    ds = load_dataset("ncbi/MedCalc-Bench-v1.0", split="test")

    # Locate columns (tolerant of naming)
    QUESTION_COL = _find_column(ds, "Question", ["question"])
    CALC_COL     = _find_column(ds, "Calculator Name",
                                ["calculator_name", "CalculatorName", "calculatorname"])

    # Group indices by question and by (question, calculator)
    by_q = {}  # preserves insertion order (first time each question appears)
    by_q_calc = defaultdict(lambda: defaultdict(list))
    all_calc_types = set()

    for idx, row in enumerate(ds):
        qval = row.get(QUESTION_COL)
        cval = row.get(CALC_COL)
        if qval not in by_q:
            by_q[qval] = []
        by_q[qval].append(idx)
        by_q_calc[qval][cval].append(idx)
        all_calc_types.add(cval)

    # Initial deterministic sample: up to PER_QUESTION per question
    rng = random.Random(SEED)
    selected_by_q = {}
    for qval, idxs in by_q.items():  # insertion order is deterministic from dataset order
        k = min(PER_QUESTION, len(idxs))
        chosen = idxs if len(idxs) <= PER_QUESTION else rng.sample(idxs, k=k)
        selected_by_q[qval] = set(chosen)

    # Build helpers for selection state
    selected_set = set()
    for s in selected_by_q.values():
        selected_set.update(s)

    # Coverage counts for calculator names in the current selection
    calc_counts = Counter(ds[i][CALC_COL] for i in selected_set)

    # Determine which calculator types are missing from the selected sample
    def _sort_key(v):
        return "" if v is None else str(v)
    missing = sorted([c for c in all_calc_types if calc_counts.get(c, 0) == 0], key=_sort_key)

    # Try to enforce coverage by swapping within question groups (keeps per-question limit)
    for m in missing:
        covered = False
        # iterate questions in deterministic order; prefer lower row indexes when swapping
        for qval in by_q:
            # candidate indices of this calculator type in this question not yet selected
            candidates = [i for i in sorted(by_q_calc[qval].get(m, [])) if i not in selected_set]
            if not candidates:
                continue

            # can we swap one of the currently selected rows in this question?
            current = sorted(selected_by_q[qval])  # deterministic order
            # choose replacement target deterministically (lowest index candidate)
            i_new = candidates[0]

            # find a replaceable currently selected index that won't break other coverage
            for j_old in current:
                old_calc = ds[j_old][CALC_COL]
                if calc_counts[old_calc] > 1:
                    # perform swap
                    selected_by_q[qval].remove(j_old)
                    selected_by_q[qval].add(i_new)
                    selected_set.remove(j_old)
                    selected_set.add(i_new)
                    calc_counts[old_calc] -= 1
                    calc_counts[m] += 1
                    covered = True
                    break

            if covered:
                break

        # If we couldn't cover m without violating the per-question limit, we leave it and continue.
        # (This is rare; usually coverage will be achievable.)
        # You could log/print a warning here if desired.

    # Finalize deterministic ordering for output
    selected_pairs = []
    for qval in by_q:
        for i in selected_by_q[qval]:
            selected_pairs.append((qval, i))
    selected_pairs.sort(key=lambda t: (_sort_key(t[0]), t[1]))
    final_indices = [i for _, i in selected_pairs]
    sampled = ds.select(final_indices)

    # Write JSON Lines to project data directory (works from src/ or project root)
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "medcalc_sample.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for ex in sampled:
            json.dump(ex, f, ensure_ascii=False)
            f.write("\n")

    # Stats
    total_count = len(sampled)
    unique_questions = len(by_q)
    # unique calculator types in the selected sample
    sample_calc_types = set(ex.get(CALC_COL) for ex in sampled)
    num_calc_types_in_sample = len(sample_calc_types)
    num_total_calc_types = len(all_calc_types)
    coverage_ok = num_calc_types_in_sample == num_total_calc_types
    max_possible = unique_questions * PER_QUESTION

    print(f"Saved file: {out_path}")
    print(f"Examples per question specified: {PER_QUESTION}")
    print(f"Unique questions: {unique_questions}")
    print(f"Maximum possible total: {max_possible} ({unique_questions} questions × {PER_QUESTION})")
    print(f"Actually downloaded: {total_count}")
    print(f"Calculator types in sample: {num_calc_types_in_sample} (of {num_total_calc_types} total) "f"{'all covered' if coverage_ok else ' not all covered'}")