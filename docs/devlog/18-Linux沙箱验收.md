# Linux 原生沙箱验收

## 做了什么

为 Linux 增加了 GitHub Actions 端到端测试，实际调用 bash、文件工具和本地 MCP，检查工作区写入、宿主目录拒写以及外部网络隔离。修复了 bash 工具错误使用进程当前目录而非 agent 工作区的问题。

## 验收过程与发现

1. Ubuntu 24.04 runner 的 AppArmor 默认策略拒绝 bubblewrap 设置网络命名空间，报 `Failed RTM_NEWADDR: Operation not permitted`。程序按设计拒绝运行；没有关闭 AppArmor 或扩大沙箱权限。
2. 改用 Ubuntu 22.04 runner 后，命名空间探针通过，测试暴露了包目录被挂到只读 `/opt` 下的问题；包挂载点移至沙箱独立的 `/tmp/minicode`。
3. 修正越界测试，使其写入只读宿主目录，而不是沙箱内允许使用的临时 `/tmp`。
4. [最终 CI 运行](https://github.com/sy-victoria/my_claude/actions/runs/45793684813)：127 通过、8 个条件跳过，Linux 原生端到端用例全部通过。

## 跟着学

1. `minicode/sandbox.py`：Linux bubblewrap 挂载与网络命名空间。
2. `minicode/agent.py` 和 `minicode/tools/bash.py`：agent 工作区传入 shell 工具。
3. `tests/test_linux_integration.py`：用真实进程验证隔离边界。
