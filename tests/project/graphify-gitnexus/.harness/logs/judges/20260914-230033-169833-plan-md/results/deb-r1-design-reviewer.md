[design-reviewer 辩论 - plan.md]

从设计架构视角，计划结构清晰但存在 3 项 major 级缺陷：技术选型缺乏对比依据、调用环检测与动态分发边界设计缺失、Tree-sitter 关键依赖待确认但 P0 无评估任务。挑战 spec-reviewer 的 INFERRED 边 over-judgment（INFERRED 在 spec.md 中有定义）和 deployment-config-reviewer 的 CI 配置 over-judgment（计划文档不应指定 CI 工具链）。

```json
{
  "satisfied": false,
  "findings": [
    {
      "id": "DR-1",
      "severity": "major",
      "confidence": 0.85,
      "title": "技术选型缺乏对比依据——BM25+RRF、置信度评分、入口点启发式均直接给出结论",
      "evidence": "T3.6/T3.7 选定 BM25+RRF(K=60) 但未提供与 TF-IDF 等替代方案的对比；T3.2 置信度 90%/60%/30% 无推导依据；T2.1 入口点评分启发式无选择依据。plan.md 直接复制 GitNexus 的选择但未论证其在 graphify 的图存储和规模上下文中的适用性。",
      "suggestion": "在 P3 任务分解前增加选型依据小节，论证 BM25/RRF/置信度/入口点启发式的选择理由。"
    },
    {
      "id": "DR-2",
      "severity": "major",
      "confidence": 0.80,
      "title": "边界与异常设计缺失——调用环检测与动态分发处理未设计",
      "evidence": "T2.2 '沿 CALLS 边从入口点 BFS' 未提及环检测：递归调用会导致 BFS 死循环。T1.4-T1.9 各语言解析器未定义如何处理动态分发（方法重写、鸭类型、接口、trait）。T1.12 将'未解析的调用'标注为 AMBIGUOUS 但未定义触发条件清单。",
      "suggestion": "T2.2 增加 BFS 环检测设计；T1.3 定义动态分发标记策略；T1.12 明确 AMBIGUOUS 触发条件清单。"
    },
    {
      "id": "DR-3",
      "severity": "major",
      "confidence": 0.90,
      "title": "Tree-sitter 关键依赖待确认但 P0 无评估任务",
      "evidence": "第10节依赖表：'Tree-sitter Python 绑定 | 如需替换现有 AST 提取为 Tree-sitter（待 P0 评估）| 待确认'。但 P0 任务（T0.1-T0.6）无一涉及 Tree-sitter 评估。此依赖影响是否需要替换 graphify 的核心 AST 提取引擎——架构级决策悬空。",
      "suggestion": "在 P0 增加 T0.0 任务：评估 graphify 现有 AST 提取是否能支持 FR-1 要求的符号类型，如不能评估 Tree-sitter 替换成本。"
    },
    {
      "id": "DR-4",
      "severity": "minor",
      "confidence": 0.70,
      "title": "P0 退出标准 CALLS 边准确率 80% 偏低，错误传播路径未设计",
      "evidence": "P0 退出标准'CALLS 边准确率（人工抽样）≥ 80%'。20% 的错误 CALLS 边会沿 P2→P3 路径传播放大。计划未说明为何 80% 可接受，以及错误案例如何识别和隔离。",
      "suggestion": "将 P0 退出标准提高到 ≥ 90%，或明确 80% 为技术可行性验证阈值，P1 需达到 ≥ 95%。"
    },
    {
      "id": "DR-5",
      "severity": "minor",
      "confidence": 0.75,
      "title": "风险应对中语言优先级与并行开发假设矛盾",
      "evidence": "风险表'按语言优先级降序实现（TS > Python > Go > Java > Rust > JS）'暗示串行实现，但 T1.4-T1.9 声明可并行开发。JavaScript 排最后但 T1.5 说'复用 TypeScript 解析器'——若 JS 依赖 TS，应紧跟 TS。",
      "suggestion": "明确语言优先级的含义（集成顺序 vs 范围裁剪保留顺序），修正 JS 位置。"
    },
    {
      "id": "DR-6",
      "severity": "minor",
      "confidence": 0.65,
      "title": "P2/P4 框架检测循环依赖导致 P2 退出标准为临时性但未标注",
      "evidence": "T2.1 '框架标记（依赖 P4 但可先用硬编码）'，T4.4 '依赖 P2 完成'。P2 使用硬编码框架标记满足 AC-4，P4 替换为真实检测。但 P2 退出标准未标注为临时验证，也未要求 P4 完成后重新验证 AC-4。",
      "suggestion": "在 P2 退出标准中标注 AC-4 为临时验证；在 P4 退出标准中增加 AC-4 回归验证。"
    }
  ],
  "summary": "计划结构清晰但存在 3 项 major 级缺陷：技术选型缺乏对比依据（DR-1）、调用环检测与动态分发边界设计缺失（DR-2）、Tree-sitter 关键依赖待确认但 P0 无评估任务（DR-3）。挑战 spec-reviewer 的 INFERRED 边 over-judgment（INFERRED 在 spec.md 中有定义，是 Part B 产生的现有边类型）和 deployment-config-reviewer 的 CI 配置 over-judgment（计划文档不应指定 CI 工具链）。建议修正后重新审查。"
}
```
