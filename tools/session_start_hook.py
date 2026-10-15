# -*- coding: utf-8 -*-
"""EAI 会话开场钩子（Claude Code SessionStart）：
读 stdin JSON → 打印 additionalContext JSON。一切异常静默退出，绝不阻塞会话。
手动测试：python session_start_hook.py --plain
"""
import json
import os
import sys
from pathlib import Path

EAI_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    try:
        try:  # 哨兵：证明钩子被调用过（排障用，追加不覆盖）
            logp = EAI_ROOT / "logs"
            logp.mkdir(exist_ok=True)
            with open(logp / "hook.log", "a", encoding="utf-8") as fh:
                fh.write(f"{__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S} invoked\n")
        except Exception:
            pass
        raw = ""
        if not sys.stdin.isatty():
            # 必须按字节读再解码 UTF-8：文本模式会用系统 ANSI 代码页（GBK）误解中文路径
            raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        data = {}
        if raw.strip():
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
        cwd = data.get("cwd") or os.getcwd()
        project = os.path.basename(str(cwd).rstrip("\\/")) or None

        sys.path.insert(0, str(EAI_ROOT / "src"))
        os.environ.setdefault("EAI_HOME", str(EAI_ROOT))
        from eai.session_brief import build_brief
        from eai.util import norm_scope

        if project:
            project = norm_scope(project)
            if project == "general":
                project = None
        brief = build_brief(project=project)
        if not brief:
            return 0
        if "--plain" in sys.argv:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            print(brief)
            return 0
        out = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": brief,
            }
        }
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(json.dumps(out, ensure_ascii=False))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
