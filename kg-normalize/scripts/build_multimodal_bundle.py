# -*- coding: utf-8 -*-
"""兼容入口（已并入 normalize.py）。归一现为单趟执行；重复调用幂等，已复核文档不会被覆盖。"""

import sys
from pathlib import Path

import normalize

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_multimodal_bundle.py <source-root> <workspace>（建议直接使用 normalize.py）")
    print("[提示] build_multimodal_bundle.py 已并入 normalize.py，本次调用将执行完整单趟归一。")
    raise SystemExit(normalize.main(Path(sys.argv[1]), Path(sys.argv[2])))
