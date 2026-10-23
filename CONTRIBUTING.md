# 参与贡献

欢迎提 issue 和 PR。这个项目的目标很小：**把长期记忆和习惯档案做成纯本地、零依赖、换模型也带得走的数据**。改动请守住这个边界。

## 环境

- Python 3.8+，git
- 不需要安装任何第三方包（整个项目只用标准库）
- Windows / macOS / Linux 都支持；Windows 是主要开发和验证平台

## 本地跑测试

```bash
python -m unittest discover -s tests -v
```

改完代码先跑测试，全绿再提交。CI 会在 Ubuntu 和 Windows 上跑 Python 3.8 / 3.11 / 3.12。

## 提交前检查

1. 测试全绿；
2. 不新增第三方依赖（标准库够用）；
3. 新逻辑同时考虑 Windows 与 POSIX 路径、编码（中文 Windows 默认 GBK，文件读写一律显式 `encoding="utf-8"`）；
4. 不把 `memory/`、`logs/`、`brief_snapshot.md`、`config.json` 提交进仓库——那是使用者的隐私数据；
5. 安装器相关改动要在临时目录试跑一次 `python tools/install.py --yes`，确认可重复执行、不重复写入已有配置。

## 报告问题

请附上：

- 操作系统与 Python 版本（`python -V`）；
- 复现步骤；
- 相关日志：`logs/` 下的文件，或命令的完整报错。

敏感信息（路径中的用户名、记忆内容）请先打码。

## 代码风格

- 纯标准库，函数保持小而直白；
- 文件读写显式指定编码；
- 面向用户的输出用中文，内部标识符用英文；
- 不引入打包工具和构建步骤，`git clone` + `python tools/install.py` 就是全部安装流程。
