"""Compare evaluation report JSON files from different model/prompt runs."""
import argparse, json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    print(f"{'REPORT':35} {'PRECISION':>10} {'RECALL':>10} {'F1':>10} {'PATCH RATE':>12}")
    for path in args.reports:
        data = json.loads(path.read_text(encoding="utf-8"))
        d, p = data["detection"], data["patches"]
        print(f"{path.name:35} {d['precision']:10.3f} {d['recall']:10.3f} {d['f1']:10.3f} {p['patch_success_rate']:12.3f}")
if __name__ == "__main__":
    main()
