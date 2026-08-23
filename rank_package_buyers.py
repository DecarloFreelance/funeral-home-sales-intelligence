#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from intelligence.package_buyer_fit import rank_package_buyers


def main():
    parser = argparse.ArgumentParser(description="Rank prospects for the complete package.")
    parser.add_argument("--input", type=Path, default=Path("data/discovered_results.json"))
    parser.add_argument("--output", type=Path, default=Path("data/package_buyer_candidates.json"))
    args = parser.parse_args()

    results = json.loads(args.input.read_text(encoding="utf-8"))
    ranked = rank_package_buyers(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(ranked, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(f"Ranked {len(ranked)} package candidates into {args.output}")
    for candidate in ranked[:10]:
        print(
            f"{candidate['buyer_fit_score']:5.1f}  "
            f"{candidate['recommended_motion']:<15}  {candidate['company']}"
        )


if __name__ == "__main__":
    main()
