# -*- coding: utf-8 -*-
"""EAI 一键安装器（Windows / Linux / macOS 通用）。

都干了什么（每一步可选，可重复运行，幂等）：
  1) 初始化本机专属记忆库（EAI 文件夹里长出你自己的全新管家）
  2) 生成开场简报快照
  3) 接入 Claude Code（会话开场自动带记忆：钩子 + CLAUDE.md 导入 + MCP 工具）
  4) 注册每晚 21:30 自动固结（可选）
  5) 回放本机历史会话成记忆（可选，需/不需 Ollama 均可）

用法：
  python tools/install.py            # 交互式
  python tools/install.py --yes      # 全部默认（自动装，不问）
  python tools/install.py --uninstall# 卸载接入（记忆数据保留）
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

IS_WIN = os.name == "nt"
HOOK_SCRIPT = ROOT / "tools" / "session_start_hook.py"
HOOK_BOOT = ROOT / "tools" / "hook_boot.bat"
LOG_DIR = ROOT / "logs"
CLAUDE_DIR = Path.home() / ".claude"
TASK_NAME = "EAI-DailyConsolidate"


def ask(question, default_yes=True, auto=False):
    if auto:
        return default_yes
    hint = "Y/n" if default_yes else "y/N"
    try:
        ans = input(f"{question} [{hint}] ").strip().lower()
    except EOFError:
        return default_yes
    if not ans:
        return default_yes
    return ans in ("y", "yes", "是", "1")


def run_eai(args, **kw):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-m", "eai", *args], cwd=str(ROOT), env=env, **kw)


# ---------------- 各步骤 ----------------

def step_init():
    print("\n[1/5] 初始化记忆库 …")
    r = run_eai(["init"], capture_output=True, text=True, errors="replace")
    print("   ", (r.stdout or r.stderr or "").strip().splitlines()[-1] if (r.stdout or r.stderr) else "完成")


def step_snapshot():
    print("[2/5] 生成开场简报快照 …")
    LOG_DIR.mkdir(exist_ok=True)
    r = run_eai(["brief"], capture_output=True, text=True, errors="replace")
    snap = ROOT / "brief_snapshot.md"
    snap.write_text((r.stdout or "").strip() + "\n", encoding="utf-8")
    print(f"    已写入 {snap.name}（{len(r.stdout or '')} 字符）")


def _hook_entry():
    log = str(ROOT / "logs" / "hook_err.log")
    if IS_WIN:
        # Windows：Claude Code 执行钩子走 PowerShell，命令必须用 PowerShell 语法；用 bat 包一层最稳
        HOOK_BOOT.write_text(
            "@echo off\n"
            "set PYTHONUTF8=1\n"
            f'"{sys.executable}" -X utf8 "%~dp0session_start_hook.py" 2>> "%~dp0..\\logs\\hook_err.log"\n',
            encoding="ascii", errors="replace")
        cmd = f'& "{HOOK_BOOT}"'
        shell = "powershell"
    else:
        cmd = f'"{sys.executable}" "{HOOK_SCRIPT}" 2>> "{log}" || true'
        shell = "bash"
    return {"matcher": "startup|resume|clear|compact",
            "hooks": [{"type": "command", "shell": shell, "command": cmd, "timeout": 30}]}


def _is_our_hook(entry):
    for h in entry.get("hooks", []):
        c = str(h.get("command", ""))
        if "session_start_hook" in c or "hook_boot" in c:
            return True
    return False


def step_claude_code():
    print("[3/5] 接入 Claude Code（开场自动带记忆 + MCP 工具）…")
    ok = True
    # 3a. settings.json 钩子
    sfile = CLAUDE_DIR / "settings.json"
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    if sfile.exists():
        shutil.copy2(sfile, sfile.with_name(f"settings.json.bak-eai-{datetime.now():%Y%m%d%H%M%S}"))
    data = {}
    if sfile.exists():
        try:
            data = json.loads(sfile.read_text(encoding="utf-8"))
        except Exception as ex:
            print(f"    settings.json 解析失败（{ex}），跳过钩子；请手动配置 hooks")
            ok = False
    if ok:
        hooks = data.setdefault("hooks", {}).setdefault("SessionStart", [])
        if any(_is_our_hook(e) for e in hooks):
            print("    SessionStart 钩子已存在，跳过")
        else:
            hooks.append(_hook_entry())
            sfile.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"    已写入 SessionStart 钩子（已备份原文件）")
    # 3b. CLAUDE.md 导入快照（兜底通道）
    cfile = CLAUDE_DIR / "CLAUDE.md"
    line = f"@{ROOT.as_posix()}/brief_snapshot.md"
    old = cfile.read_text(encoding="utf-8") if cfile.exists() else ""
    if line in old:
        print("    CLAUDE.md 导入已存在，跳过")
    else:
        with open(cfile, "a", encoding="utf-8") as fh:
            fh.write(("\n" if old and not old.endswith("\n") else "") +
                     "# EAI 管家简报（自动维护，勿删该 @ 行）\n" + line + "\n")
        print("    已追加 CLAUDE.md 导入行（每次会话自动加载管家简报）")
    # 3c. MCP 工具
    if shutil.which("claude"):
        cmd = ["claude", "mcp", "add", "-s", "user", "eai-memory", "--",
               sys.executable, str(ROOT / "src" / "eai" / "mcp_server.py")]
        if IS_WIN:
            cmd = ["cmd", "/c"] + cmd  # npm 的 claude 是 .cmd 垫片，需经 cmd 启动
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
            out = (r.stdout or "") + (r.stderr or "")
            print("    MCP：" + (out.strip().splitlines()[-1] if out.strip() else "完成"))
        except Exception as ex:
            print(f"    MCP 注册失败（可手动执行）：{ex}")
    else:
        print("    未找到 claude 命令：如需 MCP，请手动执行")
        print(f"      claude mcp add -s user eai-memory -- {sys.executable} {ROOT / 'src' / 'eai' / 'mcp_server.py'}")


def step_daily_task():
    print("[4/5] 注册每晚 21:30 自动固结 …")
    if IS_WIN:
        r = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME,
                            "/TR", f'"{ROOT / "tools" / "day.bat"}"',
                            "/SC", "DAILY", "/ST", "21:30", "/F"],
                           capture_output=True, text=True, errors="replace")
        ok = r.returncode == 0
        print("    " + ("已注册计划任务 " + TASK_NAME if ok else "注册失败（可手动跑 tools\\register_daily_task.bat）"))
    else:
        print("    请自行加入 crontab（一行）：")
        print(f"      30 21 * * * cd {ROOT} && PYTHONUTF8=1 PYTHONPATH={ROOT}/src python3 -m eai day >> {ROOT}/logs/daily.log 2>&1")


def step_replay():
    print("[5/5] 回放本机历史会话成记忆（读 ~/.claude 与 ~/.codex 转录，只读原文；无 Ollama 时走纯规则）…")
    for tool in ("harvest_claude.py", "harvest_codex.py"):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / tool)],
                           capture_output=True, text=True, errors="replace")
        lines = [l for l in ((r.stdout or "") + (r.stderr or "")).splitlines() if l.strip()]
        print("    " + (lines[-1] if lines else tool + " 无输出"))
    print("    开始固结（这一步最花时间，可随时 Ctrl+C，下次接着跑）…")
    run_eai(["consolidate"])
    print("    回放完成。以后每天 21:30 自动增量收料固结。")


# ---------------- 卸载 ----------------

def uninstall():
    print("== 卸载 EAI 接入（记忆数据一律保留）==")
    cfile = CLAUDE_DIR / "CLAUDE.md"
    if cfile.exists():
        lines = cfile.read_text(encoding="utf-8").splitlines()
        keep = [l for l in lines if "brief_snapshot.md" not in l and "EAI 管家简报（自动维护" not in l]
        cfile.write_text("\n".join(keep) + "\n", encoding="utf-8")
        print("  已移除 CLAUDE.md 导入行")
    sfile = CLAUDE_DIR / "settings.json"
    if sfile.exists():
        try:
            data = json.loads(sfile.read_text(encoding="utf-8"))
            hooks = data.get("hooks", {}).get("SessionStart", [])
            kept = [e for e in hooks if not _is_our_hook(e)]
            if len(kept) != len(hooks):
                shutil.copy2(sfile, sfile.with_name(f"settings.json.bak-eai-{datetime.now():%Y%m%d%H%M%S}"))
                data.setdefault("hooks", {})["SessionStart"] = kept
                sfile.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print("  已移除 SessionStart 钩子（已备份）")
        except Exception as ex:
            print(f"  settings.json 处理失败：{ex}")
    if shutil.which("claude"):
        cmd = ["claude", "mcp", "remove", "-s", "user", "eai-memory"]
        if IS_WIN:
            cmd = ["cmd", "/c"] + cmd
        subprocess.run(cmd, capture_output=True, text=True)
        print("  已移除 MCP（若存在）")
    if IS_WIN:
        subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True)
        print("  已删除计划任务（若存在）")
    print("  记忆本体（memory\\）与日志原样保留；不再需要时手动删整个文件夹即可。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="全部按默认执行，不询问")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()
    if a.uninstall:
        uninstall()
        return 0

    print("=" * 56)
    print("EAI 私人管家 · 一键安装")
    print(f"安装位置（记忆就长在这里）：{ROOT}")
    print(f"Python：{sys.executable}")
    print("=" * 56)

    step_init()
    step_snapshot()

    if ask("接入 Claude Code？（开场自动带记忆 + MCP 工具）", True, a.yes):
        step_claude_code()
    else:
        print("[3/5] 跳过 Claude Code 接入")

    if ask("注册每晚 21:30 自动固结？", True, a.yes):
        step_daily_task()
    else:
        print("[4/5] 跳过计划任务")

    if ask("现在回放本机历史会话成记忆？（可跳过，以后跑 `eai day` 也行）", False, a.yes):
        step_replay()
    else:
        print("[5/5] 跳过历史回放")

    print("\n完成。用法：")
    print("  双击 tools\\管家.bat（Windows）或运行 tools/eai.bat / python -m eai …")
    print("  常用命令：eai remember \"…\" / eai recall \"…\" / eai day / eai brief / eai chat")
    print("  卸载接入：python tools/install.py --uninstall（记忆不删）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
