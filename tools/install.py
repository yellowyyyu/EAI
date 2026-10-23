# -*- coding: utf-8 -*-
"""EAI 一键安装器（Windows / Linux / macOS 通用）。

装完的效果：新开一个 Claude Code 或 Codex 会话，它已经知道使用者的习惯、
记得以前发生过的事，不需要使用者开口提醒。

都干了什么（每一步可选，可重复运行，幂等）：
  1) 初始化本机专属记忆库（EAI 文件夹里长出你自己的全新管家）
  2) 生成开场简报快照
  3) 初始化四本习惯档案 + 写入全局说明（Claude Code 的 CLAUDE.md）
  4) 接入 Claude Code（SessionStart 钩子 + MCP 工具）
  5) 接入 Codex（AGENTS.md + MCP 工具）
  6) 注册每晚 21:30 自动固结（可选）
  7) 回放历史会话 + 导入已有项目记忆（可选）

用法：
  python tools/install.py            # 交互式
  python tools/install.py --yes      # 全部默认（自动装，不问）
  python tools/install.py --uninstall# 卸载接入（记忆与档案数据保留）
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
RUN_EAI = ROOT / "tools" / "run_eai.py"
LOG_DIR = ROOT / "logs"
CLAUDE_DIR = Path.home() / ".claude"
CODEX_DIR = Path.home() / ".codex"
PROFILE_DIR = CLAUDE_DIR / "user-profile"
TEMPLATES = ROOT / "templates"
TASK_NAME = "EAI-DailyConsolidate"
# 沙箱测试用：跳过会动到系统全局的步骤（外部 claude 命令、计划任务）
SKIP_MCP = os.environ.get("EAI_SKIP_MCP") == "1"
SKIP_TASK = os.environ.get("EAI_SKIP_TASK") == "1"

BLOCK_BEGIN = "<!-- EAI:BEGIN（本区块由 EAI 安装器自动维护；重装会覆盖，手改请写在区块外） -->"
BLOCK_END = "<!-- EAI:END -->"


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


def _posix(p: Path) -> str:
    return Path(p).as_posix()


# ---------------- 区块读写 ----------------

def upsert_block(path: Path, block: str) -> str:
    """把 EAI 区块写入文件：已有区块则整块替换，没有则追加。返回动作说明。"""
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if old and "<!-- EAI:BEGIN" not in old:
        shutil.copy2(path, path.with_name(f"{path.name}.bak-eai-{datetime.now():%Y%m%d%H%M%S}"))
    lines = old.splitlines()
    kept, inside, found = [], False, False
    for line in lines:
        s = line.strip()
        if s.startswith("<!-- EAI:BEGIN"):
            inside = True
            found = True
            continue
        if inside and s.startswith("<!-- EAI:END"):
            inside = False
            continue
        if not inside:
            kept.append(line)
    body = "\n".join(kept).rstrip()
    if body:
        body += "\n\n"
    body += block.strip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return "已更新" if found else "已写入"


def remove_block(path: Path) -> bool:
    if not path.exists():
        return False
    old = path.read_text(encoding="utf-8")
    lines, inside, changed = [], False, False
    for line in old.splitlines():
        s = line.strip()
        if s.startswith("<!-- EAI:BEGIN"):
            inside = True
            changed = True
            continue
        if inside and s.startswith("<!-- EAI:END"):
            inside = False
            continue
        if not inside:
            lines.append(line)
    if changed:
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return changed


# ---------------- 区块内容 ----------------

def claude_block() -> str:
    home = _posix(Path.home())
    profile = _posix(PROFILE_DIR)
    eai = _posix(ROOT)
    return f"""{BLOCK_BEGIN}
# 角色：私人管家

你是使用者的长期私人管家。模型只是引擎，记忆和人格是数据；目标是越用越懂使用者。
不确定的事先查记忆再开口；新学到的事实、决定、纠正、承诺默认写入记忆；长期习惯写进档案。

# 习惯档案（每次会话自动加载，长期自动维护）

@{profile}/speech-style.md
@{profile}/personal-glossary.md
@{profile}/image-preferences.md
@{profile}/task-habits.md
@{eai}/brief_snapshot.md

上面四行是使用者的四本习惯档案，最后一行是管家开场简报，每次会话自动加载。

## 档案维护规则（已授权自动记录，不必逐条询问）

1. **主动留意**：对话中留意四类信号——表达/汇报偏好、特殊说法的含义、图片图表喜好、任务做法或纠正。发现值得长期保留的，当场写入对应档案，不必等提醒。
2. **纠正必记**：使用者纠正过的事，必须记入档案，以后严格执行，不再犯。
3. **格式**：每条一行 `- [YYYY-MM-DD] 内容`；只记长期习惯，不记一次性事务；相同内容不重复记；新旧矛盾以新的为准，删掉旧的。
4. **保持精简**：每本档案尽量不超过 60 行，变长时合并同类项、压缩措辞。
5. **优先级**：档案里的习惯优先于常规默认做法；有冲突时以档案为准。
6. **展示**：使用者说"看看习惯档案"（或类似说法）时，按四类用大白话逐条念，不照读格式符号。
7. **隐私**：档案只存本机，不上传、不外发。
8. **兜底**：若某次对话里看不到档案内容（没有自动加载），做任务前先 Read 这四个文件。
9. **分工**：长期习惯进档案；事件、进展、项目状态进记忆系统，两者互补。

# 长期记忆（EAI，默认使用，不需要使用者提醒）

- 开场简报已经自动注入（上面的 brief_snapshot.md）；需要更多历史背景时用 recall 查。
- 命令：`python "{eai}/tools/run_eai.py" recall "关键词"`、`python "{eai}/tools/run_eai.py" remember "内容" -k <类型>`；装了 MCP 时也有同名工具。
- 类型：fact / preference / correction / decision / promise / project / skill / episode。
- 对话中新学到的内容默认写入记忆，不等使用者提醒；写入前先 recall 查重。
{BLOCK_END}"""


def agents_block() -> str:
    profile = _posix(PROFILE_DIR)
    eai = _posix(ROOT)
    run = _posix(RUN_EAI)
    return f"""{BLOCK_BEGIN}
# 角色：私人管家

你是使用者的长期私人管家。模型只是引擎，记忆和人格是数据；目标是越用越懂使用者。

# 每次会话开始时自动执行（不要等使用者提醒，也不要报告你在做这些）

1. 读取开场简报：`{eai}/brief_snapshot.md`
2. 读取四本习惯档案：
   - `{profile}/speech-style.md`
   - `{profile}/personal-glossary.md`
   - `{profile}/image-preferences.md`
   - `{profile}/task-habits.md`
3. 把以上内容作为你的角色、背景和工作方式。需要历史细节时查记忆：
   `python "{run}" recall "关键词"`

# 档案维护规则（已授权自动记录）

- 对话中留意表达偏好、特殊说法、图片喜好、任务做法与纠正；值得长期保留的当场写入对应档案。
- 每条一行 `- [YYYY-MM-DD] 内容`；只记长期习惯；相同不重复；新旧矛盾以新的为准。
- 每本不超过 60 行；档案优先于常规默认做法；档案只存本机，不外发。
- 长期习惯进档案；事件、决定、项目状态进记忆。

# 长期记忆（EAI）

- 新学到的事实、决定、纠正、承诺默认写入：`python "{run}" remember "内容" -k fact`
- 查历史：`python "{run}" recall "关键词"`；类型：fact/preference/correction/decision/promise/project/skill/episode
- 写入前先 recall 查重；不需要使用者提醒。
{BLOCK_END}"""


# ---------------- 各步骤 ----------------

def step_init():
    print("\n[1/7] 初始化记忆库 …")
    r = run_eai(["init"], capture_output=True, text=True, errors="replace")
    print("   ", (r.stdout or r.stderr or "").strip().splitlines()[-1] if (r.stdout or r.stderr) else "完成")


def step_snapshot():
    print("[2/7] 生成开场简报快照 …")
    LOG_DIR.mkdir(exist_ok=True)
    r = run_eai(["brief"], capture_output=True, text=True, errors="replace")
    snap = ROOT / "brief_snapshot.md"
    snap.write_text((r.stdout or "").strip() + "\n", encoding="utf-8")
    print(f"    已写入 {snap.name}（{len(r.stdout or '')} 字符）")


def step_profile():
    print("[3/7] 初始化习惯档案 + 写入全局说明 …")
    src = TEMPLATES / "user-profile"
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    copied, kept = [], []
    for tpl in sorted(src.glob("*.md")):
        dst = PROFILE_DIR / tpl.name
        if dst.exists():
            kept.append(tpl.name)
        else:
            shutil.copy2(tpl, dst)
            copied.append(tpl.name)
    if copied:
        print(f"    已创建档案：{'、'.join(copied)}")
    if kept:
        print(f"    已存在，保留不动：{'、'.join(kept)}")
    action = upsert_block(CLAUDE_DIR / "CLAUDE.md", claude_block())
    print(f"    CLAUDE.md 角色与档案区块{action}（{_posix(CLAUDE_DIR / 'CLAUDE.md')}）")


def _hook_entry():
    log = str(ROOT / "logs" / "hook_err.log")
    if IS_WIN:
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
    print("[4/7] 接入 Claude Code（开场自动带记忆 + MCP 工具）…")
    ok = True
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
            print("    已写入 SessionStart 钩子（已备份原文件）")
    if SKIP_MCP:
        print("    已按测试模式跳过 MCP 注册")
    elif shutil.which("claude"):
        cmd = ["claude", "mcp", "add", "-s", "user", "eai-memory", "--",
               sys.executable, str(ROOT / "src" / "eai" / "mcp_server.py")]
        if IS_WIN:
            cmd = ["cmd", "/c"] + cmd
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
            out = (r.stdout or "") + (r.stderr or "")
            print("    MCP：" + (out.strip().splitlines()[-1] if out.strip() else "完成"))
        except Exception as ex:
            print(f"    MCP 注册失败（可手动执行）：{ex}")
    else:
        print("    未找到 claude 命令：如需 MCP，请手动执行")
        print(f"      claude mcp add -s user eai-memory -- {sys.executable} {ROOT / 'src' / 'eai' / 'mcp_server.py'}")


def _codex_mcp_toml() -> str:
    return ("\n[mcp_servers.eai-memory]\n"
            f'command = {json.dumps(sys.executable)}\n'
            f'args = [{json.dumps(str(ROOT / "src" / "eai" / "mcp_server.py"))}]\n')


def step_codex():
    print("[5/7] 接入 Codex（开场自动读档案 + MCP 工具）…")
    CODEX_DIR.mkdir(parents=True, exist_ok=True)
    action = upsert_block(CODEX_DIR / "AGENTS.md", agents_block())
    print(f"    AGENTS.md 角色与档案区块{action}（{_posix(CODEX_DIR / 'AGENTS.md')}）")
    cfg = CODEX_DIR / "config.toml"
    old = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    if "[mcp_servers.eai-memory]" in old:
        print("    config.toml 里已有 eai-memory MCP，跳过")
    else:
        if cfg.exists():
            shutil.copy2(cfg, cfg.with_name(f"config.toml.bak-eai-{datetime.now():%Y%m%d%H%M%S}"))
        with open(cfg, "a", encoding="utf-8") as fh:
            if old and not old.endswith("\n"):
                fh.write("\n")
            fh.write(_codex_mcp_toml())
        print("    config.toml 已写入 eai-memory MCP（已备份）")


def step_daily_task():
    print("[6/7] 注册每晚 21:30 自动固结 …")
    if SKIP_TASK:
        print("    已按测试模式跳过计划任务")
    elif IS_WIN:
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
    print("[7/7] 回放历史会话 + 导入已有项目记忆 …")
    for tool in ("harvest_claude.py", "harvest_codex.py"):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / tool)],
                           capture_output=True, text=True, errors="replace")
        lines = [l for l in ((r.stdout or "") + (r.stderr or "")).splitlines() if l.strip()]
        print("    " + (lines[-1] if lines else tool + " 无输出"))
    imported = _import_project_memories()
    if imported:
        print(f"    已导入已有项目记忆 {imported} 条")
    print("    开始固结（这一步最花时间，可随时 Ctrl+C，下次接着跑）…")
    run_eai(["consolidate"])
    print("    回放完成。以后每天 21:30 自动增量收料固结。")


def _import_project_memories() -> int:
    """把 ~/.claude/projects/*/memory/*.md 里已有的项目记忆导入 EAI（按内容去重）。"""
    base = CLAUDE_DIR / "projects"
    if not base.is_dir():
        return 0
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "import json,sys\n"
        "from eai.store import MemoryStore\n"
        "s=MemoryStore(); n=0\n"
        "for rec in json.load(sys.stdin):\n"
        "    s.add(rec)\n"
        "    n+=1\n"
        "s.close(); print(n)\n"
    )
    records = []
    for p in sorted(base.glob("*/memory/*.md")):
        if p.name.upper() == "MEMORY.MD":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if text.lstrip().startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                text = parts[2]
        text = text.strip()
        if len(text) < 20:
            continue
        records.append({"kind": "project", "title": p.stem[:80],
                        "text": text[:4000], "scope": p.parent.parent.name[:80]})
    if not records:
        return 0
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env,
                       input=json.dumps(records, ensure_ascii=False),
                       capture_output=True, text=True, errors="replace")
    try:
        return int((r.stdout or "0").strip().splitlines()[-1])
    except Exception:
        return 0


# ---------------- 卸载 ----------------

def uninstall():
    print("== 卸载 EAI 接入（记忆与档案数据一律保留）==")
    if remove_block(CLAUDE_DIR / "CLAUDE.md"):
        print("  已移除 CLAUDE.md 里的 EAI 区块")
    if remove_block(CODEX_DIR / "AGENTS.md"):
        print("  已移除 AGENTS.md 里的 EAI 区块")
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
        print("  已移除 Claude Code 的 MCP（若存在）")
    cfg = CODEX_DIR / "config.toml"
    if cfg.exists():
        text = cfg.read_text(encoding="utf-8")
        marker = "\n[mcp_servers.eai-memory]"
        if marker in text:
            head, _, tail = text.partition(marker)
            rest = tail.split("\n[", 1)
            tail2 = ("\n[" + rest[1]) if len(rest) == 2 else ""
            shutil.copy2(cfg, cfg.with_name(f"config.toml.bak-eai-{datetime.now():%Y%m%d%H%M%S}"))
            cfg.write_text(head.rstrip() + "\n" + tail2, encoding="utf-8")
            print("  已移除 Codex 的 MCP 配置（已备份）")
    if IS_WIN:
        subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True)
        print("  已删除计划任务（若存在）")
    print("  记忆本体（memory/）、档案（~/.claude/user-profile/）原样保留；不再需要时手动删文件夹即可。")


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
    step_profile()

    if ask("接入 Claude Code？（开场自动带记忆 + MCP 工具）", True, a.yes):
        step_claude_code()
    else:
        print("[4/7] 跳过 Claude Code 接入")

    if ask("接入 Codex？（开场自动读档案 + MCP 工具）", True, a.yes):
        step_codex()
    else:
        print("[5/7] 跳过 Codex 接入")

    if ask("注册每晚 21:30 自动固结？", True, a.yes):
        step_daily_task()
    else:
        print("[6/7] 跳过计划任务")

    if ask("现在回放历史会话 + 导入已有项目记忆？（可跳过，以后跑 `eai day` 也行）", False, a.yes):
        step_replay()
    else:
        print("[7/7] 跳过历史回放")

    print("\n完成。新开一个 Claude Code 或 Codex 会话，直接问它：\"报一下你现在记得我什么。\"")
    print("  常用命令：python tools/run_eai.py remember \"…\" / recall \"…\" / day / brief")
    print("  卸载接入：python tools/install.py --uninstall（记忆与档案不删）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
