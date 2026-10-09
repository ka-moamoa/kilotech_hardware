"""Ask the KiloTech advisor through the cluster.

    python tools/ask.py "When should I plant kalo?"
    python tools/ask.py "..." --task rag --model qwen2.5:7b --gateway http://gateway-host:8000
"""
import argparse
import json

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query")
    parser.add_argument("--gateway", default="http://localhost:8000")
    parser.add_argument("--task", default="kilotech_rag")
    parser.add_argument("--model", default=None, help="default: the worker's default model")
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()

    spec = {"task": args.task, "model": args.model, "input": {"query": args.query}}
    response = httpx.post(f"{args.gateway}/v1/generate", json=spec,
                          params={"timeout_s": args.timeout}, timeout=args.timeout + 30)
    job = response.json()
    if response.status_code != 200:
        print(f"HTTP {response.status_code}:", json.dumps(job, indent=2))
        return

    output, metrics = job["output"], job["metrics"]
    if output.get("weather"):
        print(f"[weather] {output['weather']}\n")
    print(output["response"])
    print(f"\n[{job['worker_id']} | {output.get('model')} | queued {metrics.get('queue_wait_s')}s"
          f" | ran {metrics.get('run_s')}s | attempt {job['attempt']}]")
    for source in output.get("sources", []):
        print(f"  - {source['collection']}/{source['source']}:{source['line']}  ({source['score']:.3f})")


if __name__ == "__main__":
    main()
