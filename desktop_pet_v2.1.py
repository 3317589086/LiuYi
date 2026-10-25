# -*- coding: utf-8 -*-
"""六一桌宠 v2.1 启动器（双击这个文件即可运行）。

真正的代码已经拆进 ragdollpet/ 包：
    config / assets / frames / bubble / pet / app
这里只负责把包所在目录加进 sys.path，然后启动。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ragdollpet.app import main        # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
