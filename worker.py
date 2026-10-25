"""워커 노드(PC방 PC 1대를 흉내냄).

실행: python worker.py --id pc-01 [--master http://127.0.0.1:8000] [--seat-prob 0.02]

유휴 감지 시뮬레이션:
- 매 step 직전에 확률(--seat-prob)로 '손님이 착석'한 것으로 처리
- 또는 이 폴더에 `seat_<id>` 파일을 만들면 수동으로 착석을 발생시킬 수 있음
착석하면 체크포인트를 저장하고 작업을 반환한 뒤, --seat-secs 동안 작업을 받지 않는다.
실제 서비스에서는 이 부분을 키보드/마우스 입력 감지 에이전트로 교체한다.
"""
import argparse
import json
import os
import random
import time
import urllib.request

from common import run_step


def call(master, path, payload=None):
    req = urllib.request.Request(
        master + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def seat_taken(worker_id, prob):
    flag = f"seat_{worker_id}"
    if os.path.exists(flag):
        os.remove(flag)
        return True
    return random.random() < prob


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--master", default="http://127.0.0.1:8000")
    ap.add_argument("--seat-prob", type=float, default=0.0)
    ap.add_argument("--seat-secs", type=float, default=0.5)
    args = ap.parse_args()

    while True:
        try:
            res = call(args.master, f"/task?worker={args.id}")
        except OSError:
            time.sleep(1)
            continue
        task = res.get("task")
        if task is None:
            if res.get("finished"):
                print(f"[{args.id}] 전체 작업 종료, 워커 종료")
                return
            time.sleep(0.5)
            continue

        done, inside = task["done_steps"], task["inside"]
        interrupted = False
        for step in range(done, task["steps"]):
            if seat_taken(args.id, args.seat_prob):
                call(args.master, "/checkpoint", {"worker": args.id, "task": task["id"],
                                                  "done_steps": done, "inside": inside, "release": True})
                print(f"[{args.id}] 손님 착석! 조각 {task['id']} 를 {done}/{task['steps']} 에서 저장하고 반환")
                time.sleep(args.seat_secs)
                interrupted = True
                break
            inside += run_step(task["id"], step)
            done = step + 1
            if done % 2 == 0:  # 2 step마다 체크포인트 겸 하트비트
                r = call(args.master, "/checkpoint", {"worker": args.id, "task": task["id"],
                                                      "done_steps": done, "inside": inside})
                if r.get("error"):  # 소유권을 잃음(회수됨)
                    interrupted = True
                    break
        if not interrupted:
            call(args.master, "/complete", {"worker": args.id, "task": task["id"], "inside": inside})


if __name__ == "__main__":
    main()
