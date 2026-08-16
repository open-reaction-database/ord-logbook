# Copyright 2026 Open Reaction Database Project Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Benchmark a reaction classifier over a file of reaction SMILES.

Usage: bench.py {rxc|ri} reactions.smi out.json [limit]

Reports: model-load time, steady-state throughput, per-reaction latency,
label coverage, and peak RSS. Emits a JSON summary and a per-reaction label
list (for cross-classifier agreement analysis).
"""
import json
import resource
import sys
import time


def peak_rss_mb() -> float:
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports kilobytes.
    return ru / (1024 * 1024) if sys.platform == "darwin" else ru / 1024


def pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, int(q * len(sorted_vals)))
    return sorted_vals[i]


def main():
    mode, path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else None

    with open(path) as fh:
        rxns = [ln.strip() for ln in fh if ln.strip()]
    if limit:
        rxns = rxns[:limit]

    # --- model load (import + init) ---
    t0 = time.perf_counter()
    if mode == "rxc":
        from reactionclassifier import ReactionClassifier

        clf = ReactionClassifier()

        def classify(smi):
            r = clf.classify(smi)
            # confirmed label, neural fallback label
            return r.reaction_code, r.neural_code
    elif mode == "ri":
        from rxn_insight.reaction import Reaction
        from rxnmapper import RXNMapper

        mapper = RXNMapper()

        def classify(smi):
            info = Reaction(smi, rxn_mapper=mapper).get_reaction_info()
            name = info.get("NAME")
            cls = info.get("CLASS")
            confirmed = name if (name and name != "OtherReaction") else None
            return confirmed, cls
    else:
        raise SystemExit(f"unknown mode {mode}")
    load_s = time.perf_counter() - t0

    # --- warm up (compile templates / prime caches) ---
    if rxns:
        try:
            classify(rxns[0])
        except Exception:
            pass

    # --- steady state ---
    confirmed = 0          # deterministically confirmed (rxc) / specific name (ri)
    fallback_only = 0      # gate/class present but not confirmed
    failed = 0             # exception or no label at all
    labels = []
    latencies = []
    t_start = time.perf_counter()
    for smi in rxns:
        t = time.perf_counter()
        try:
            conf, coarse = classify(smi)
        except Exception:
            conf, coarse = None, None
            failed += 1
            latencies.append(time.perf_counter() - t)
            labels.append(None)
            continue
        latencies.append(time.perf_counter() - t)
        labels.append(conf if conf else (f"~{coarse}" if coarse else None))
        if conf:
            confirmed += 1
        elif coarse:
            fallback_only += 1
        else:
            failed += 1
    steady_s = time.perf_counter() - t_start

    latencies.sort()
    n = len(rxns)
    summary = {
        "mode": mode,
        "n": n,
        "load_seconds": round(load_s, 2),
        "steady_seconds": round(steady_s, 2),
        "throughput_rxn_per_s": round(n / steady_s, 2) if steady_s else None,
        "latency_ms_median": round(1000 * pct(latencies, 0.50), 2),
        "latency_ms_p90": round(1000 * pct(latencies, 0.90), 2),
        "confirmed": confirmed,
        "confirmed_pct": round(100 * confirmed / n, 1) if n else 0,
        "fallback_only": fallback_only,
        "fallback_only_pct": round(100 * fallback_only / n, 1) if n else 0,
        "failed": failed,
        "failed_pct": round(100 * failed / n, 1) if n else 0,
        "peak_rss_mb": round(peak_rss_mb(), 1),
    }
    with open(out_path, "w") as fh:
        json.dump({"summary": summary, "labels": labels}, fh)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
