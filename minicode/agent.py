"""核心 agent 循环 —— 全项目最重要的文件，将在 M1 实现。

预告（详见 docs/00-roadmap.md M1 与 docs/01-architecture.md 第 1 节）：
agent 的本质是 `LLM + 工具 + 循环`，唯一状态是一个 messages 列表：

    messages.append(用户输入)
    loop:
        response = client.messages.create(model, messages, tools=...)
        messages.append(response 的 assistant 内容块)
        if response.stop_reason != "tool_use":
            return  # 模型说完了，把话筒还给用户
        for 每个 tool_use 块:
            result = 执行对应工具（异常要捕获，错误文本也返回给模型）
            messages.append(role=user 的 tool_result 块)
        # 继续 loop，把工具结果喂回模型
"""
