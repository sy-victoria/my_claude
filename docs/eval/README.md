# ForgeCode 评测

固定样本为 SWE-bench Lite `dev` 的 5 个实例，数据集修订版本与 ID 写在 `swebench-lite-dev5.json`。官方 Lite 开发集共 23 个实例；本样本只用于相同条件下比较版本，不代表完整 Lite 榜单成绩。样本来源：[官方数据集](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite)。

## 运行

在 Linux x86_64、已配置 Docker 与模型服务的机器上，另装可选评测依赖 `pip install datasets swebench`。评测工作区用 `.eval-output/`；每个实例只拉取其 `base_commit`，提示词只包含问题描述，不传入标准补丁。

```bash
python -m minicode.eval run --output .eval-output --provider openai --model YOUR_MODEL
python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Lite --split dev \
  --predictions_path .eval-output/predictions.json --run_id forgecode-dev5
python -m minicode.eval report --metrics .eval-output/metrics.json \
  --official-results logs/evaluation/forgecode-dev5/results.json
```

将 `--provider openai` 换为 `ollama` 可接本机模型；云模型通过环境变量提供 API Key。官方评判需单独准备容器资源，[官方文档](https://www.swebench.com/SWE-bench/guides/evaluation/)说明了 Docker 运行方式。运行过程中逐实例写入预测和指标文件；中断后保留已有结果供检查。

固定同一模型、样本、预算和运行环境，用改造前后的两个提交分别运行，再用 `python -m minicode.eval compare --baseline-metrics ... --baseline-official-results ... --candidate-metrics ... --candidate-official-results ...` 比较解决率、Token、工具调用和时间。故障注入运行 `python -m minicode.eval fault --output .eval-output/fault.json`；它在模型响应、工具开始、写入后、工具完成和结果落盘边界模拟中断，检查不会重放状态不明的写入。跨文件修改由本仓库 `tests/test_eval.py` 的合成仓库用例验证，因为 Lite 的筛选条件排除了多文件改动任务。

`metrics.json` 的 `recovery_success_rate` 只有在记录了恢复尝试时才有数值；普通模型评测不注入中断，因此为 `null`。真实模型评测可能产生模型费用和较大的 Docker 缓存；CI 仅运行离线测试。
