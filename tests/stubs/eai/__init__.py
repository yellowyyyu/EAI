# -*- coding: utf-8 -*-
"""EAI 依赖模块的最小桩包（仅测试用）。

对应 specs/10_core.md 里冻结的接口，用最朴素的实现顶上，
供 tests/test_mcp.py 在正式模块就绪前测试 mcp_server 的协议行为。
正式实现由主程写在 src/eai/ 下，本桩包不得替代它。

用法：把 tests/stubs 放进 PYTHONPATH（或在测试里拼进子进程的 sys.path），
`import eai.store` 等就会落到这里。
"""
