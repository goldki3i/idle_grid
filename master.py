"""마스터 노드: 작업 분할, 분배, 체크포인트 저장, 장애/착석 시 재할당.

실행: python master.py [--port 8000]
API
  POST /submit      {"total_steps": 480, "chunks": 12}   작업 제출 (chunks개로 분할)
  GET  /task?worker=ID                                     워커가 할 일 요청
  POST /checkpoint  {"worker","task","done_steps","inside","release"}  진행 상황 저장
  POST /complete    {"worker","task","inside"}             작업 조각 완료
  GET  /status                                             진행 현황
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from common import SAMPLES_PER_STEP

LEASE_SEC = 5  # 이 시간 동안 체크포인트(하트비트)가 없으면 워커가 죽은 것으로 보고 회수

lock = threading.Lock()
job = None
events = []


def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    events.append(line)
    print(line, flush=True)


def reclaim_expired():
    now = time.time()
    for t in job["tasks"].values():
        if t["state"] == "running" and now > t["lease"]:
            log(f"조각 {t['id']}: {t['worker']} 응답 없음 -> 체크포인트({t['done_steps']}/{t['steps']})부터 재할당 대기")
            t["state"], t["worker"] = "pending", None


def make_job(total_steps: int, chunks: int):
    per = total_steps // chunks
    return {
        "started": time.time(),
        "finished": None,
        "tasks": {
            i: {"id": i, "steps": per, "done_steps": 0, "inside": 0,
                "state": "pending", "worker": None, "lease": 0.0, "resumes": 0}
            for i in range(chunks)
        },
    }


def status():
    tasks = job["tasks"].values() if job else []
    done = [t for t in tasks if t["state"] == "done"]
    total_samples = sum(t["steps"] for t in tasks) * SAMPLES_PER_STEP
    out = {
        "submitted": job is not None,
        "chunks_total": len(list(tasks)),
        "chunks_done": len(done),
        "resumes": sum(t["resumes"] for t in tasks),
        "finished": bool(job and job["finished"]),
        "events": events[-30:],
    }
    if job and job["finished"]:
        inside = sum(t["inside"] for t in tasks)
        out["pi"] = 4.0 * inside / total_samples
        out["inside"] = inside
        out["elapsed_sec"] = round(job["finished"] - job["started"], 2)
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 기본 접근 로그 끄기
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        global job
        url = urlparse(self.path)
        with lock:
            if url.path == "/status":
                return self._send(status())
            if url.path == "/task":
                worker = parse_qs(url.query).get("worker", ["?"])[0]
                if job is None:
                    return self._send({"task": None, "finished": False})
                reclaim_expired()
                for t in job["tasks"].values():
                    if t["state"] == "pending":
                        resumed = t["done_steps"] > 0
                        t.update(state="running", worker=worker, lease=time.time() + LEASE_SEC)
                        if resumed:
                            t["resumes"] += 1
                            log(f"조각 {t['id']}: {worker} 가 체크포인트 {t['done_steps']}/{t['steps']} 부터 이어서 실행")
                        else:
                            log(f"조각 {t['id']}: {worker} 에 할당 (steps={t['steps']})")
                        return self._send({"task": {k: t[k] for k in ("id", "steps", "done_steps", "inside")},
                                           "finished": False})
                return self._send({"task": None, "finished": bool(job["finished"])})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        global job, events
        url = urlparse(self.path)
        data = self._body()
        with lock:
            if url.path == "/submit":
                events = []
                job = make_job(int(data["total_steps"]), int(data["chunks"]))
                log(f"작업 제출: {data['total_steps']} steps -> {data['chunks']} 조각")
                return self._send({"ok": True})
            if job is None:
                return self._send({"error": "no job"}, 400)
            t = job["tasks"].get(int(data.get("task", -1)))
            if t is None or t["worker"] != data.get("worker"):
                return self._send({"error": "not owner"}, 409)  # 이미 회수된 조각
            if url.path == "/checkpoint":
                t["done_steps"], t["inside"] = int(data["done_steps"]), int(data["inside"])
                t["lease"] = time.time() + LEASE_SEC
                if data.get("release"):
                    log(f"조각 {t['id']}: {t['worker']} 손님 착석 -> 체크포인트 저장({t['done_steps']}/{t['steps']}) 후 반환")
                    t["state"], t["worker"] = "pending", None
                return self._send({"ok": True})
            if url.path == "/complete":
                t["done_steps"], t["inside"], t["state"] = t["steps"], int(data["inside"]), "done"
                log(f"조각 {t['id']}: {data['worker']} 완료")
                if all(x["state"] == "done" for x in job["tasks"].values()):
                    job["finished"] = time.time()
                    log("전체 작업 완료, 결과 병합")
                return self._send({"ok": True})
        self._send({"error": "not found"}, 404)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    print(f"마스터 노드 실행: http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
