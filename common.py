"""마스터와 워커가 공유하는 작업 정의.

작업 예시: 몬테카를로로 원주율(pi) 추정.
- 전체 작업 = total_steps 개의 step, 각 step은 SAMPLES_PER_STEP 개의 샘플
- step의 난수 시드를 (task_id, step)으로 고정해서, 어느 노드가 어디서 재개하든 결과가 같다.
  -> 체크포인트 이어하기가 정확한지 검증할 수 있다.
"""
import random

SAMPLES_PER_STEP = 150_000


def run_step(task_id: int, step: int) -> int:
    """step 하나를 계산하고 원 안에 들어간 점의 개수를 반환."""
    rng = random.Random(task_id * 1_000_003 + step)
    inside = 0
    for _ in range(SAMPLES_PER_STEP):
        x, y = rng.random(), rng.random()
        if x * x + y * y <= 1.0:
            inside += 1
    return inside
