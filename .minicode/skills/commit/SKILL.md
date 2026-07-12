---
name: commit
description: 检查当前 git 改动并生成规范的 commit 提交。用户想提交代码、说"帮我提交"时使用。
---
请完成一次规范的 git 提交，步骤：

1. 用 bash 运行 `git status --short` 和 `git diff --stat` 查看当前改动
2. 如果没有任何改动，告知用户后结束，不要空提交
3. 根据改动内容总结一条简洁的中文 commit message，格式：`<类型>: <一句话说明>`
   （类型可选：feat / fix / docs / refactor / test / chore）
4. `git add` 相关文件并用生成的 message 提交
5. 用 `git log --oneline -1` 确认提交成功，把 commit 信息告诉用户

用户的补充要求（可能为空）：$ARGUMENTS
