[spec-reviewer 辩论 - plan.md]

从规格审查视角，plan.md 存在 3 个 major 级问题：NFR-5/NFR-6 未定义、AC 缺乏量化阈值、MCP 工具接口契约不完整。与 design-reviewer 的核心发现高度重合并互相印证。

```json
{
  "satisfied": false,
  "findings": [
    {
      "id": "SR-1",
      "severity": "major",
      "confidence": 0.9,
      "category": "traceability",
      "title": "NFR-5/NFR-6 被附录映射到 P1 但全文未定义",
      "evidence": "附录声明 P1 覆盖 NFR-4/NFR-5/NFR-6，但 plan.md 全文从未说明 NFR-5/NFR-6 的具体内容。P1 退出标准仅提及 AC-1/AC-2/AC-3，不包含对 NFR-5/NFR-6 的验证。",
      "suggestion": "在计划中内联 NFR-5/NFR-6 的定义摘要，并在 P1 退出标准中增加对应验证条件。"
    },
    {
      "id": "SR-2",
      "severity": "major",
      "confidence": 0.85,
      "category": "testability",
      "title": "多项验收标准缺乏量化通过阈值",
      "evidence": "AC-4 '完整调用链'未定义判定标准；AC-8 '混合搜索优于纯向量'未定义优势幅度；AC-10 '语义连贯性'仅用'人工审查'无评分细则。",
      "suggestion": "为每个 AC 定义明确的通过阈值：AC-4 覆盖率≥90%；AC-8 召回率提升≥X%；AC-10 评分细则。"
    },
    {
      "id": "SR-3",
      "severity": "major",
      "confidence": 0.8,
      "category": "interface-contract",
      "title": "新增 MCP 工具接口契约不完整",
      "evidence": "T3.5 注册 context/impact/trace/detect_changes 四个工具，但未定义输入参数 schema、输出格式、错误码。AC-7 仅验证'可调用'，不覆盖接口契约完整性。",
      "suggestion": "为每个 MCP 工具定义输入/输出 JSON schema 和错误码。"
    },
    {
      "id": "SR-4",
      "severity": "minor",
      "confidence": 0.75,
      "title": "NFR-2 在 P2 和 P5 双重映射且无通过阈值",
      "evidence": "附录将 NFR-2 映射到 P2 和 P5，但两个阶段的退出标准均未给出增量更新耗时的通过阈值。T5.3 仅'记录耗时'无判定标准。",
      "suggestion": "明确 NFR-2 的主要验证阶段，在退出标准中定义通过阈值。"
    },
    {
      "id": "SR-5",
      "severity": "minor",
      "confidence": 0.7,
      "title": "T2.1 对 P4 的前向引用与阶段依赖声明不一致",
      "evidence": "T2.1 '依赖 P4 但可先用硬编码'，T4.4 '依赖 P2 完成'，形成潜在循环引用，与串行依赖图矛盾。",
      "suggestion": "明确 T2.1 的 P4 依赖是软依赖还是硬依赖。"
    },
    {
      "id": "SR-6",
      "severity": "minor",
      "confidence": 0.65,
      "title": "LanguageResolver 接口未定义方法签名",
      "evidence": "T1.3 声明实现 LanguageResolver 接口，但接口的方法签名、输入/输出类型未定义。",
      "suggestion": "在 T1.3 交付物中明确 LanguageResolver 接口定义。"
    }
  ],
  "summary": "从规格审查视角，plan.md 存在 3 个 major 级问题：NFR-5/NFR-6 未定义、AC 缺乏量化阈值、MCP 工具接口契约不完整。与 design-reviewer 的核心发现高度重合并互相印证。建议在进入实现阶段前补齐 NFR 定义、AC 阈值和接口契约。"
}
```
