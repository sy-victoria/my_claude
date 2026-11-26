# macOS Docker 沙箱验收

## 做了什么

在 GitHub 的 macOS Intel runner 启动 Colima Docker 引擎，缓存项目要求的 Python 容器镜像，运行完整测试集及真实 shell、文件、网络和本地 MCP 集成测试。测试使用共享给 Colima 的仓库目录作为临时工作区。

## 遇到的问题

第一次运行时，pytest 在 `/private/var/...` 下创建临时目录，Colima 没有共享该宿主目录。Docker 拒绝 bind mount，导致文件工具和 hooks 的 5 个测试失败。把 `TMPDIR` 设为仓库内的 `.pytest-tmp` 后，容器能访问临时工作区，且工作区仍限定在已共享的项目目录内。

## 验收

- [macOS CI 运行](https://github.com/sy-victoria/my_claude/actions/runs/45796325397)：132 通过、3 个 Linux 专属测试跳过。
- Windows 本机 Docker 集成测试先前已通过；macOS 运行证明同一 Docker 后端在两种桌面平台均可执行实际工具。
- 使用者需要确保项目目录已共享给本地 Docker 引擎；缺少共享时容器会拒绝挂载。

## 跟着学

1. `.github/workflows/macos-sandbox.yml`：看 CI 如何启动 Colima 并准备共享工作区。
2. `minicode/sandbox.py`：看桌面 Docker 的挂载、网络和资源限制。
3. `tests/test_docker_integration.py`：看真实容器的文件和网络验收。
