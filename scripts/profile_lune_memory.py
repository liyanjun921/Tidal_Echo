"""Sample the real HTTP E2E backend on Linux; all model/voice calls use fixtures.

Run with the project's Python environment and its existing LUNE_LATENT_SOURCE /
LUNE_PASSIVE_MODEL_CACHE. This measures processes, not a container memory limit.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def processes():
    result = {}
    for directory in Path("/proc").iterdir():
        if not directory.name.isdigit():
            continue
        try:
            stat = (directory / "stat").read_text().rsplit(")", 1)[1].split()
            command = (directory / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            result[int(directory.name)] = (int(stat[1]), command, directory)
        except (OSError, ValueError, IndexError):
            pass  # A sampled process may exit between reads.
    return result


def sample(parent_host):
    table = processes()
    runners = {pid for pid, (parent, command, _) in table.items()
               if parent == parent_host and "tests/run_e2e.py" in command}
    selected = {pid for pid, (parent, command, _) in table.items()
                if parent in runners and "scripts/run_lune.py" in command}
    while True:
        grown = selected | {pid for pid, (parent, _, _) in table.items() if parent in selected}
        if grown == selected:
            break
        selected = grown
    rows = []
    for pid in sorted(selected):
        try:
            _, command, directory = table[pid]
            memory = {}
            for line in (directory / "smaps_rollup").read_text().splitlines():
                parts = line.split()
                if ":" in line and len(parts) >= 2 and parts[1].isdigit():
                    memory[parts[0].rstrip(":")] = int(parts[1])
            label = next((name for name in ("latent_worker.py", "latent_jobs.py", "api_loop:app",
                         "backend.lune_server:app", "scripts/run_lune.py") if name in command),
                         "other backend child")
            rows.append({"process": label, "rss_kib": memory["Rss"], "pss_kib": memory["Pss"],
                         "swap_kib": memory.get("Swap", 0)})
        except (OSError, ValueError, KeyError):
            pass
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Linux /proc with readable smaps_rollup is required")
    if not os.environ.get("LUNE_LATENT_SOURCE") or not os.environ.get("LUNE_PASSIVE_MODEL_CACHE"):
        parser.error("Set both native source and local model cache paths to profile full Latent")
    root = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=True)
    # /proc may show host PIDs while Popen.pid is in a nested PID namespace.
    parent_host = int(next(line.split()[1] for line in Path("/proc/self/status").read_text().splitlines()
                           if line.startswith("Pid:")))
    started, samples = time.monotonic(), []
    with (args.output / "e2e.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "tests/run_e2e.py", "--http-only"],
                                   cwd=root, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while process.poll() is None:
                rows = sample(parent_host)
                if rows:
                    samples.append({"seconds": round(time.monotonic() - started, 2),
                                    "rss_kib": sum(row["rss_kib"] for row in rows),
                                    "pss_kib": sum(row["pss_kib"] for row in rows), "processes": rows})
                if time.monotonic() - started > 220:
                    raise TimeoutError("Profile exceeded 220 seconds")
                time.sleep(.15)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    if not samples:
        raise RuntimeError("No backend memory samples collected; no memory conclusion is valid")
    report = {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
              "platform": os.uname().machine, "test_exit_code": process.returncode,
              "duration_seconds": round(time.monotonic() - started, 2), "sample_interval_seconds": .15,
              "sample_count": len(samples), "peak_pss": max(samples, key=lambda row: row["pss_kib"]),
              "peak_rss": max(samples, key=lambda row: row["rss_kib"]),
              "limitations": ["Local Linux process-tree sampling, not a Render container or cgroup limit test.",
                              "Excludes synthetic model/MCP fixtures and test clients.",
                              "Includes original local BGE model, native workers and native archive jobs.",
                              "Sampled PSS/RSS excludes unsampled peaks and additional cgroup filesystem/page-cache overhead.",
                              "Small synthetic corpus, cached assets and synthetic provider; no real account or API credentials."]}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return process.returncode


if __name__ == "__main__":
    sys.exit(main())
