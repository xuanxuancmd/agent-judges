[design-reviewer 最终裁决 - plan.md]

独立审查 plan.md 全文及 2 轮辩论记录后，确认 4 项 major 设计缺陷：技术选型缺乏对比依据、边界与异常设计缺失、Tree-sitter 依赖悬空、MCP 工具接口契约不完整。综合判定：major，8 findings。

```json
{
  "severity": "major",
  "confidence": 0.86,
  "reasoning": "独立审查 plan.md 全文及 2 轮辩论记录后，确认设计在结构上完整，但在 4 个维度存在实质性设计缺陷，足以导致实施阶段返工或质量不可控。",
  "findings": [
    {
      "description": "技术选型缺乏对比依据——BM25+RRF(K=60)、置信度 90%/60%/30%、入口点评分启发式均直接给出结论",
      "severity": "major",
      "confidence": 0.88,
      "evidence": "T3.6/T3.7 选定 BM25+RRF 未提供与替代方案对比；T3.2 置信度无推导依据；T2.1 入口点评分无权重选择依据。",
      "suggestion": "在 P3 启动前增加选型依据小节，论证选择理由。"
    },
    {
      "description": "边界与异常设计缺失——调用环检测、动态分发处理、AMBIGUOUS 触发条件均未设计",
      "severity": "major",
      "confidence": 0.84,
      "evidence": "T2.2 BFS 未提及环检测；T1.4-T1.9 未定义动态分发处理；T1.12 AMBIGUOUS 触发条件未列举。",
      "suggestion": "T2.2/T3.3 增加 visited-set 环检测；T1.3 定义动态分发标记策略；T1.12 明确 AMBIGUOUS 触发条件清单。"
    },
    {
      "description": "Tree-sitter 关键依赖待确认但 P0 无评估任务",
      "severity": "major",
      "confidence": 0.90,
      "evidence": "第10节 Tree-sitter 待确认但 P0 任务无评估。若需替换整个 P1 方案前提不成立。",
      "suggestion": "在 P0 增加 T0.0 任务：评估现有 AST 提取能力，如不足评估 Tree-sitter 替换成本。"
    },
    {
      "description": "MCP 工具接口契约不完整——4 个新工具无参数 schema、输出格式、错误码定义",
      "severity": "major",
      "confidence": 0.82,
      "evidence": "T3.5 仅声明工具名，未定义接口契约。AC-7 仅验证'可调用'未覆盖响应格式。",
      "suggestion": "在 T3.5 增加每个 MCP 工具的接口契约定义。"
    },
    {
      "description": "P0 退出标准 CALLS 边准确率 80% 偏低，错误边会沿 P2→P3 传播放大",
      "severity": "minor",
      "confidence": 0.78,
      "evidence": "P0 退出标准 80%。20% 错误 CALLS 边进入 P2/P3 导致结果失真。",
      "suggestion": "将 P0 退出标准提高到 ≥ 90%。"
    },
    {
      "description": "语言优先级与并行开发假设矛盾",
      "severity": "minor",
      "confidence": 0.76,
      "evidence": "风险表暗示串行但 T1.4-T1.9 声明可并行。JS 排最后但复用 TS。",
      "suggestion": "明确语言优先级含义，修正 JS 位置。"
    },
    {
      "description": "P2/P4 框架检测循环依赖——P2 硬编码框架标记，P4 替换，P2 退出标准未标注临时性",
      "severity": "minor",
      "confidence": 0.78,
      "evidence": "T2.1 硬编码框架标记，T4.4 替换。P2 退出标准 AC-4 未标注为临时验证。",
      "suggestion": "在 P2 退出标准标注 AC-4 为临时验证；P4 增加 AC-4 回归验证。"
    },
    {
      "description": "依赖锁定策略缺失影响 NFR-5 确定性",
      "severity": "minor",
      "confidence": 0.72,
      "evidence": "第10节依赖表未提及版本锁定。不同环境行为可能不一致。",
      "suggestion": "在 P0 或 P1 早期增加依赖锁定任务。"
    }
  ],
  "satisfied": false
}
```
