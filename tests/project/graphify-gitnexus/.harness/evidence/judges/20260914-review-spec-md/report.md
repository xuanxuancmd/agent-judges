# 对抗审查报告

> 路由档位: **thorough** — 渐进式审查: 7636 tok → 哨兵单审 → 面板扩张; thorough 续跑 (存在 critical 发现 (severity=critical, 加权置信度=0.87))

## 最终裁决

- **严重程度**: critical
- **置信度**: 0.64 (原始 0.90, 元审查校准后)
- **是否通过**: ❌ 否
- **⚠️ 需要人工介入** (`escalate_to_human: true`)

### 发现 (18)

> 按置信度升序排列（低置信度 = 机器不确定 = 人工优先检查）。

1. **[major]** (置信度: 0.75)
   - 依据: C:\wanglong\graphify\Dockerfile 与 pyproject.toml 已存在。新建竞争模块将打包进同一 Docker 镜像，MCP serve.py 工具注册表出现功能重叠工具。

2. **[major]** (置信度: 0.75)
   - 依据: 500 文件 60s 无基线数据
   - 建议: P0 阶段增加基线测量

3. **[major]** (置信度: 0.78)
   - 依据: 非目标 4.2.1 不引入 LadybugDB 无理由；RRF K=60 无依据；NFR-3 3倍无建模
   - 建议: 补充对比分析

4. **[major]** (置信度: 0.82)
   - 依据: FR-4 定义单边置信度但未定义多跳路径合成规则
   - 建议: 定义乘积模型或最小值模型

5. **[major]** (置信度: 0.85)
   - 依据: hybrid_scorer.py（337行）已实现 HybridScorer 向量+模糊混合评分。serve.py:17 导入，serve.py:130 实例化，serve.py:632 在 query 工具中调用。plan.md T3.7 计划新建 hybrid_search.py——竞争配置接口。

6. **[major]** (置信度: 0.85)
   - 依据: FR-1 要求限定名但未定义 6 种语言的构成规则
   - 建议: 在 FR-1 或附录中定义每语言的限定名规则

7. **[critical]** (置信度: 0.88)
   - 依据: symbol_resolution.py（556行）已实现 ImportedSymbol dataclass、build_label_index()、parse_python_import_aliases()。resolver_registry.py 注册 LanguageResolver。affected.py DEFAULT_AFFECTED_RELATIONS 含 inherits/extends/implements。

8. **[major]** (置信度: 0.88)
   - 依据: spec FR-2 定义大写 CALLS/IMPORTS/HERITAGE/DEFINES，代码使用小写 calls/imports/inherits/implements/embeds/extends。spec 未定义迁移策略。
   - 建议: 明确边类型命名规范，设计迁移路径

9. **[critical]** (置信度: 0.90)
   - 依据: §3.2 标记'缺融合层'，但 hybrid_scorer.py:191 HybridScorer 已实现向量+词法+模糊三层融合，已接入 serve.py MCP query
   - 建议: 修正 §3.2 表格为'已实现（向量+模糊融合），缺 BM25+RRF'

10. **[major]** (置信度: 0.90)
   - 依据: FR-3/FR-4 涉及 CALLS 边遍历但未定义循环检测。spec-reviewer 独立佐证。
   - 建议: 定义 visited-set 环检测+最大遍历深度

11. **[critical]** (置信度: 0.92)
   - 依据: §3.2 标记'完全缺失'，但 affected.py:190 affected_nodes() 已实现 blast radius + 深度分组，cli.py:1667 已注册 affected 命令
   - 建议: 修正 §3.2 表格为'已实现'

12. **[critical]** (置信度: 0.92)
   - 依据: §3.2 标记'完全缺失'，但 callflow_html.py:1608 write_callflow_html() 已实现调用流程可视化
   - 建议: 修正 §3.2 表格为'已实现'

13. **[critical]** (置信度: 0.92)
   - 依据: spec.md 第130行：'影响分析 | 无 | 完全缺失'。实际 affected.py（318行）已实现 AffectedHit dataclass（含 depth/via_relation）。cli.py:1667 注册 affected 命令。serve.py:1884 注册 get_pr_impact MCP 工具。plan.md T3.1 计划新建 impact_analyzer.py——双实现+CLI命令冲突。

14. **[critical]** (置信度: 0.93)
   - 依据: §3.2 标记'完全缺失'，但 graphify resolution.py:822 _apply_symbol_resolution_facts() 已实现跨文件 calls 边解析
   - 建议: 修正 §3.2 表格为'已实现'，引用源码位置

15. **[critical]** (置信度: 0.93)
   - 依据: §3.2 标记'完全缺失'，但 resolution.py:1984 resolve_import() 已实现 named/default/wildcard/namespace import
   - 建议: 修正 §3.2 表格为'已实现'

16. **[critical]** (置信度: 0.93)
   - 依据: §3.2 标记'完全缺失'，但 resolution.py:1080 已处理 inherits/implements 边
   - 建议: 修正 §3.2 表格为'已实现'

17. **[critical]** (置信度: 0.95)
   - 依据: plan.md 第70行：'T1.3 | 实现语言解析器注册机制：LanguageResolver 接口 + 每语言实现 | 交付物 resolver_registry.py'。实际 C:\wanglong\graphify\graphify\resolver_registry.py（85行）已实现 LanguageResolver dataclass 及注册机制。文件名完全相同，接口定义完全相同。

18. **[critical]** (置信度: 0.95)
   - 依据: affected.py（318行）实现 blast radius+深度分组，cli.py:1667 注册 affected 命令；resolver_registry.py（85行）实现 LanguageResolver 注册机制，plan.md T1.3 交付物同名；symbol_resolution.py（556行）实现跨文件符号解析+导入解析；hybrid_scorer.py（337行）实现向量+模糊混合评分，serve.py:130 已接入；callflow_html.py 实现调用流程可视化。spec §3.2 将这些标记为'完全缺失'。
   - 建议: 基于 graphify 源码重写 §3.2 对标表，将 FR-1/FR-2/FR-4/FR-6/FR-7 从'新建'重新定位为'增强/完善'

> ⚠️ 置信度 0.64 低于阈值 0.8,建议人工复核低置信度发现。

## 指标

- 共识度 (consensus): 1.0
- 稳定性 (stability): 1.0

## 元审查校准

- 校准后置信度: 0.64 (原始 0.90)
- 元审查严重程度: critical
- 元审查置信度: 0.79
