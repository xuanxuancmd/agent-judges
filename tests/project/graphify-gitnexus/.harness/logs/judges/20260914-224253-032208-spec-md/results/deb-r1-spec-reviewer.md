[spec-reviewer 辩论回复 - Round 1]

spec-reviewer 在辩论阶段审视了 deployment-config-reviewer 和 design-reviewer 的 findings，提出挑战与辩护。主要挑战：(1) deployment-config-reviewer 将可运维性 NFR 缺失定为 minor 偏低，应升级为 major（spec 包含运行时服务组件）；(2) 同意 design-reviewer 关于架构选型、AC 覆盖、异常路径的发现并扩展（AC-10 存在 FR 追溯断裂）。

```json
{
  "satisfied": false,
  "findings": [
    {
      "id": "SR-1",
      "severity": "major",
      "confidence": 0.85,
      "title": "验收标准覆盖不完整：FR-8 及多个 NFR 缺少对应 AC，FR-2 四种边类型仅两种有 AC",
      "evidence": "第7节验收标准表仅定义 AC-1 至 AC-10。FR-8（框架检测）无对应 AC；NFR-1（性能）、NFR-2（增量耗时）、NFR-3（存储）、NFR-5（确定性）、NFR-6（诚实性）均无 AC。FR-2 定义 CALLS/IMPORTS/HERITAGE/DEFINES 四种边类型，但仅 AC-2（CALLS）和 AC-3（IMPORTS）有覆盖，HERITAGE 和 DEFINES 无 AC。此外 AC-10（社区检测语义连贯性）对应的能力不在任何 FR 中定义，存在 AC→FR 追溯断裂。",
      "suggestion": "为 FR-8 及 NFR-1/2/3/5/6 补充验收标准；为 FR-2 的 HERITAGE 和 DEFINES 边补充 AC；将 AC-10 关联到具体 FR 或新增 FR。每个 AC 应明确判定方法与通过阈值。"
    },
    {
      "id": "SR-2",
      "severity": "major",
      "confidence": 0.80,
      "title": "接口契约不完整：新增 MCP 工具、边类型、process 节点均缺少数据模式定义",
      "evidence": "FR-6 定义 context/impact/trace/detect_changes 四个 MCP 工具，但未定义任何工具的输入参数 schema 和输出响应 schema。FR-2 定义 CALLS/IMPORTS/HERITAGE/DEFINES 边类型但未定义边的数据字段（除 source/target 外的字段如调用位置、参数信息等）。FR-3 process 节点'应包含：入口点符号、调用链步骤列表、覆盖的符号集合'但未给出结构化定义。FR-4 影响分析未定义返回格式（深度分层的具体 JSON 结构）。",
      "suggestion": "为每个 MCP 工具定义输入/输出 JSON schema；为新增边类型定义数据字段规范；为 process 节点和 impact 分析结果定义结构化数据模式。"
    },
    {
      "id": "SR-3",
      "severity": "major",
      "confidence": 0.82,
      "title": "边界条件未显式覆盖：递归调用链、循环依赖终止条件、深度限制均缺失",
      "evidence": "FR-3 执行流追踪'沿 CALLS 边从入口点出发，构建有向调用子图'，但未定义循环依赖终止条件或最大追踪深度。FR-4 影响分析'按调用深度分层'但未定义最大深度或 budget 限制。FR-5 git-diff 影响映射'沿 CALLS/HERITAGE 边传播影响'但未定义传播终止条件。对于存在循环调用（A→B→A）的代码库，无终止条件的图遍历将产生无限循环或无限增长的 process 节点。",
      "suggestion": "为 FR-3/FR-4/FR-5 定义最大深度/budget 参数、循环检测机制（visited set 或 SCC 折叠），以及超限时的截断行为与输出标记。"
    },
    {
      "id": "SR-4",
      "severity": "minor",
      "confidence": 0.75,
      "title": "部分验收标准不可客观测试：含主观判定词或缺少量化阈值",
      "evidence": "AC-8 'RRF 融合结果的召回率不低于纯向量搜索'未定义测试数据集、查询集与召回率计算方法。AC-10 '社区划分应与代码的功能模块划分基本一致'中'基本一致'为主观判定，无客观度量标准。AC-1 '检查节点类型完整性'未定义'完整性'的判定标准。",
      "suggestion": "为 AC-8 定义标准测试数据集与召回率计算公式；为 AC-10 定义量化度量（如模块覆盖率、ARI/NMI 指数）；为 AC-1 明确每种语言应覆盖的符号类型清单作为判定基准。"
    },
    {
      "id": "SR-5",
      "severity": "minor",
      "confidence": 0.70,
      "title": "规格内部一致性：悬空边与 AMBIGUOUS 边语义未区分",
      "evidence": "FR-2 说明：'跨文件引用解析在增量更新场景下可能产生短暂的悬空边'。NFR-6：'跨文件解析未能解析的调用应标注为 AMBIGUOUS，不应静默丢弃'。这两条规则未区分'瞬时悬空边'（时序问题，下次 --update 可修复）与'永久未解析引用'（符号确实不存在）。",
      "suggestion": "明确区分两种情况：瞬时悬空边标注为 PENDING 或 EXTRACTED+stale 标记并定义消解时机；永久未解析标注为 AMBIGUOUS。"
    },
    {
      "id": "SR-6",
      "severity": "minor",
      "confidence": 0.65,
      "title": "NFR-3 存储增长阈值（3 倍）缺乏计算依据",
      "evidence": "NFR-3：'graph.json 在新增跨文件边后，体积增长不应超过原有体积的 3 倍'。对于大型代码库，CALLS 边数量可能远超节点数量，3 倍阈值的计算基础未说明。",
      "suggestion": "提供 3 倍阈值的计算依据（基于典型代码库的边/节点比统计），或改为分语言/分规模的差异化阈值。"
    }
  ],
  "challenges": [
    {
      "target": "deployment-config-reviewer",
      "finding_ref": "NFR 未覆盖可运维性需求",
      "position": "disagree_severity",
      "reasoning": "deployment-config-reviewer 将此定为 minor，但该 spec 明确定义了 MCP stdio server（FR-6，运行时服务组件）和外部服务集成，可运维性 NFR（至少健康检查与日志策略）应在规格层面定义。建议升级为 major。"
    },
    {
      "target": "deployment-config-reviewer",
      "finding_ref": "BM25 倒排索引未指定存储路径",
      "position": "agree",
      "reasoning": "minor 合理。"
    },
    {
      "target": "deployment-config-reviewer",
      "finding_ref": "外部服务依赖未定义配置接口",
      "position": "agree_and_extend",
      "reasoning": "配置接口缺失是真实缺口，且属于规格层面的接口契约不完整。"
    },
    {
      "target": "design-reviewer",
      "finding_ref": "关键架构选型缺乏对比依据（graph.json vs LadybugDB）",
      "position": "agree",
      "reasoning": "非目标 4.2#1 仅陈述决定，未给出技术理由。"
    },
    {
      "target": "design-reviewer",
      "finding_ref": "验收标准覆盖不完整",
      "position": "agree_and_extend",
      "reasoning": "补充：AC-10（社区检测语义连贯性）对应的能力不在任何 FR 中定义，存在 AC→FR 追溯断裂。"
    },
    {
      "target": "design-reviewer",
      "finding_ref": "异常路径与失败模式设计不足",
      "position": "agree",
      "reasoning": "FR-3 循环依赖终止条件缺失、FR-2 悬空边消解方案缺失，与 SR-3 和 SR-5 一致。"
    },
    {
      "target": "design-reviewer",
      "finding_ref": "NFR-1 大规模仓库性能指标不可度量",
      "position": "agree",
      "reasoning": "'可接受范围'未定义任何数值约束。"
    }
  ],
  "summary": "该规格文档在结构完整性和方向清晰性上表现良好，但在规格审查的核心维度上存在系统性缺陷：(1) 验收标准覆盖不完整——6+ 项 FR/NFR 无 AC；(2) 接口契约缺失（MCP 工具与边类型无 schema 定义）；(3) 边界条件未覆盖（循环依赖、深度限制缺失）；(4) 部分验收标准不可客观测试。deployment-config-reviewer 对可运维性 NFR 缺失的严重度评定偏低（应升级为 major）。design-reviewer 的发现整体准确，与本审查者的发现高度一致。"
}
```
