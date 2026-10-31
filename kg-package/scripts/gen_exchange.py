# -*- coding: utf-8 -*-
"""兼容入口：从冻结知识包生成通用交换态投影。"""

import sys
from pathlib import Path

from export_kb import main


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python gen_exchange.py <工作区目录>")
        raise SystemExit(1)
    workspace = Path(sys.argv[1])
    main(workspace, workspace / "80-知识库导出")
