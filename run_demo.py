"""원클릭 데모: 마스터 1 + 워커 N을 띄우고, 작업을 제출한 뒤, 단일 노드 실행과 비교한다.

실행: python run_demo.py [--workers 4] [--seat-prob 0.03]
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

from common import SAMPLES_PER_STEP, run_step

PORT = 8765
MASTER = f"http://127.0.0.1:{PORT}"


def post(path, payload):
    req = urllib.request.Request(MASTER + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())


def get(path):
    return json.loads(urllib.request.urlopen(MASTER + path).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 2))
    ap.add_argument("--steps", type=int, default=240)
    ap.add_argument("--chunks", type=int, default=12)
    ap.add_argument("--seat-prob", type=float, default=0.02)
    args = ap.parse_args()

    print(f"== 1) 단일 노드 기준선: {args.steps} steps 순차 실행")
    t0 = time.time()
    inside_ref = sum(run_step(c, s) for c in range(args.chunks) for s in range(args.steps // args.chunks))
    single = time.time() - t0
    pi_ref = 4.0 * inside_ref / (args.steps * SAMPLES_PER_STEP)
    print(f"   pi={pi_ref:.6f}, 소요 {single:.2f}s\n")

    print(f"== 2) PC방 분산 실행: 워커 {args.workers}대, 착석 확률 {args.seat_prob}/step")
    procs = [subprocess.Popen([sys.executable, "master.py", "--port", str(PORT)], stdout=subprocess.DEVNULL)]
    try:
        for _ in range(50):
            try:
                get("/status")
                break
            except OSError:
                time.sleep(0.1)
        post("/submit", {"total_steps": args.steps, "chunks": args.chunks})
        for i in range(args.workers):
            procs.append(subprocess.Popen([sys.executable, "worker.py", "--id", f"pc-{i+1:02d}",
                                           "--master", MASTER, "--seat-prob", str(args.seat_prob)]))
        while not get("/status")["finished"]:
            time.sleep(0.3)
        st = get("/status")
        for line in st["events"]:
            print("  ", line)
        print(f"\n   pi={st['pi']:.6f}, 소요 {st['elapsed_sec']}s, 체크포인트 재개 {st['resumes']}회")
        print("\n== 3) 검증")
        print(f"   결과 일치(체크포인트 이어하기 정확성): {st['inside'] == inside_ref}")
        print(f"   속도 향상: {single / st['elapsed_sec']:.2f}x (워커 {args.workers}대)")
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
