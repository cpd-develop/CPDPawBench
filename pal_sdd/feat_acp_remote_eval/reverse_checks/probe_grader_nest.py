"""Read-only: does a leftover wrapper nest, multiplying later prints?"""
from __future__ import annotations
import subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
REPO = Path("/Users/anderson/Desktop/ClawParterner/CPDPawBench")
sys.path.insert(0, str(REPO))
from pawbench.grader import _grade_automated
REAL = sys.modules["subprocess"]
MARK = "FAKE-NEST-do-not-use-5c19"
ROUNDS = 3
SLEEP = 0.20
body = f"import time\ndef grade(t, w):\n    time.sleep({SLEEP})\n    return {{'ok': 1}}\n"
item = SimpleNamespace(task_id="sleeper", automated_checks=f"```python\n{body}\n```")
def one():
    _grade_automated(item, {"transcript": [], "workspace": ""})
for _ in range(ROUNDS):
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(one); time.sleep(0.05); b = pool.submit(one)
        a.result(); b.result()
import subprocess as later
print("WRAPPED" if later is not REAL else "INTACT", flush=True)
later.run(["echo", MARK], capture_output=True, text=True)
