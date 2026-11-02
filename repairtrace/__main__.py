"""Small inspection CLI; no inference, replay or automatic semantic judgment."""
import argparse
import json


def main():
    parser = argparse.ArgumentParser(prog="repairtrace")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Inspect a version 0.1 JSONL trace")
    inspect.add_argument("trace")
    demo = sub.add_parser("demo", help="CPU demo (requires Linux user namespaces)")
    demo.add_argument("--trace", default="demo.jsonl")
    args = parser.parse_args()
    if args.command == "demo":
        from .demo import run
        print(json.dumps(run(args.trace), indent=2))
    else:
        with open(args.trace, encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
        if not records:
            parser.error("Empty trace")
        for i, record in enumerate(records):
            if record.get("schema_version") != "0.1" or record.get("step") != i or record.get("run_id") != records[0].get("run_id"):
                parser.error("Unsupported schema or inconsistent sequence/run identity")
        print(json.dumps({"events": len(records), "run_id": records[0]["run_id"],
                          "timeline": records}, indent=2))


if __name__ == "__main__":
    main()
