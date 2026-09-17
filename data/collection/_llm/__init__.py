"""LLM 实验采集的内部库（下划线前缀：不被 replication/run_all.py 自动执行）。

模块职责：
    config     配置与环境变量加载、项目路径
    io_utils   哈希、时间、JSONL 追加写、断点续跑
    design     联合实验任务的随机化引擎
    render     提示词与任务屏渲染
    providers  DeepSeek / 智谱 / 火山 / OpenAI / Anthropic 的统一调用接口
"""

from __future__ import annotations

__all__ = ["config", "io_utils", "design", "render", "providers"]
