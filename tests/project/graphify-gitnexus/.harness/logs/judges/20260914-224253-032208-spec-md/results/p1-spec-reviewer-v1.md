Now I have the complete task prompt. Let me carefully review the spec.md content as a spec-reviewer. My persona is:
- 审查规格文档(spec)
- 关注可追溯性、接口契约完整性、边界条件、验收标准可测试性、内部一致性

My checklist:
- 每条需求可追溯到具体规格条目
- 接口契约定义完整(含异常路径)
- 边界条件显式列出
- 验收标准可执行
- 规格内部无矛盾

Let me systematically analyze the spec.

The spec is about "在 graphify 图谱基础上对标 GitNexus 补齐能力" - extending graphify's knowledge graph capabilities to match GitNexus's code intelligence capabilities.

Let me go through each FR and NFR carefully:

**FR-1：符号级 AST 索引增强**
- 符号类型：函数、方法、类、接口、类型别名、变量声明、模块/命名空间 (7 types listed)
- 语言：TypeScript、JavaScript、Python、Go、Java、Rust (6 languages)
- 每个符号节点应包含：符号名、限定名、文件路径、起止行号、符号类别
- AST 提取保持确定性、无 LLM 依赖
- 优先级 P1

AC-1: "FR-1 符号提取覆盖 6 种语言的函数/类/方法/接口" - but FR-1 lists 7 symbol types (函数、方法、类、接口、类型别名、变量声明、模块/命名空间). The AC only mentions 4 (函数/类/方法/接口). This is a traceability gap - the AC doesn't verify all symbol types claimed in FR-1.

**FR-2：跨文件调用与引用边解析**
- CALLS, IMPORTS, HERITAGE, DEFINES edges
- Based on language-aware rules, no LLM
- New edges tagged EXTRACTED
- Note about dangling edges in incremental update scenarios

AC-2: CALLS edges
AC-3: IMPORTS edges (named/default/wildcard)
But where's AC for HERITAGE and DEFINES edges? No AC covers these two edge types. This is a traceability gap.

**FR-3：执行流追踪**
- Entry point identification (heuristic scoring, configurable)
- Call chain tracing along CALLS edges
- Process node includes: entry point symbol, call chain steps, covered symbol set
- Multiple entry points

AC-4 covers this.

**FR-4：影响分析工具**
- Downstream impact (along CALLS direction)
- Upstream impact (reverse CALLS direction)
- Confidence scoring based on edge source
- Result grouping by depth

AC-5 covers this.

**FR-5：增量更新引擎增强**
- Git diff (file + line level) → affected symbols
- Propagate along CALLS/HERITAGE edges
- Coordinate with existing --update
- MCP tool detect_changes

AC-6 covers this.

**FR-6：MCP 工具集扩展**
- context, impact, trace, detect_changes
- Keep existing query/path/explain

AC-7 covers this.

**FR-7：混合搜索增强**
- BM25 inverted index
- Semantic search via existing embeddings
- RRF fusion, K=60 default, configurable
- Results include symbol node references

AC-8 covers this.

**FR-8：框架检测与入口点配置**
- Framework detection via AST pattern matching
- No LLM
- Results feed into entry point scoring (FR-3)
- Rules configurable, extensible

No AC for FR-8! This is a major traceability gap - FR-8 has no acceptance criterion.

**NFRs:**
- NFR-1: Performance (500 files in 60s, 5000 files "acceptable range")
- NFR-2: Incremental update time, git-diff in seconds
- NFR-3: Storage (graph.json growth ≤3x, BM25 as sidecar)
- NFR-4: Backward compatibility
- NFR-5: Determinism
- NFR-6: Honesty

AC-9 covers NFR-4.
AC-10 covers community detection semantic coherence - but this isn't tied to any specific FR/NFR! Community detection is listed as existing capability in section 2.2, not as a new requirement. So AC-10 verifies an existing capability, not a new requirement.

No AC for NFR-1 (performance), NFR-2 (incremental time), NFR-3 (storage), NFR-5 (determinism), NFR-6 (honesty). These are significant gaps.

**Milestones:**
- M1: P0 prototype - cross-file call resolution (single language: TypeScript)
- M2: P1 - FR-1 + FR-2
- M3: P2 - FR-3 + FR-5
- M4: P3 - FR-4 + FR-6 + FR-7
- M5: P4 - FR-8
- M6: P5 - performance, large-scale, docs

Wait, FR-3 is P2 priority, but M3 says "FR-3 执行流追踪 + FR-5 git-diff 影响映射". FR-5 depends on FR-3 (process nodes) and FR-2 (CALLS/HERITAGE edges). M3 is after M2 which delivers FR-2. That's fine.

But FR-4 is P3 and in M4, and it depends on FR-2 (CALLS edges) which is in M2. That's fine.

FR-6 in M4, but FR-6 includes `impact` tool (FR-4) and `detect_changes` (FR-5). Since FR-4 and FR-5 are in M3 (before M4), the dependencies are satisfied. Good.

But wait - FR-8 (P4, M5) says "检测结果作为入口点评分的输入信号之一（FR-3）". FR-3 is in M3 (before M5). So FR-8 depends on FR-3 being already implemented. That's fine chronologically. But it means FR-3's entry point scoring won't have framework detection input until M5. This creates a temporal inconsistency - FR-3 claims entry point scoring should be "可配置、可扩展" but the framework detection that feeds into it comes later.

Actually, this is a design dependency issue - FR-3 is supposed to use framework detection (FR-8) as input, but FR-8 is delivered two milestones later. The spec doesn't address how FR-3 works before FR-8 is available.

Now let me look for more issues:

**Interface contracts:**
- FR-2 mentions CALLS, IMPORTS, HERITAGE, DEFINES edges but doesn't define the edge schema (source node type, target node type, properties). For example, what's the source/target of an IMPORTS edge? File → Module? File → Symbol? This is underspecified.
- FR-3 process node structure is defined (entry point symbol, call chain steps, covered symbol set) but "调用链步骤列表" is not specified - what does each step contain? Just the symbol reference? The edge? The depth?
- FR-4 confidence scoring: mentions [CALLS 90%] example, but the mapping from edge source to confidence is only loosely defined ("EXTRACTED 边高置信、INFERRED 边中置信、AMBIGUOUS 边低置信"). What are the actual numeric values?
- FR-5 git-diff input format: "接收 git diff（文件级 + 行级）" - but doesn't specify the input format. Is it unified diff? JSON? What's the API contract?
- FR-6 MCP tools: each tool's input parameters and output schema are not defined. For `context`, what are the input parameters? Just a symbol name? Qualified name? What's the output JSON schema?
- FR-7: "搜索结果应包含符号节点引用" - what's the format of the reference? Node ID? Qualified name?

**Boundary conditions:**
- FR-2 mentions dangling edges in incremental updates (good), but doesn't specify how they're handled (just noted as inherent). What happens when a query traverses a dangling edge?
- FR-3: What happens with recursive call chains (A calls B, B calls A)? Cycle detection? Depth limit?
- FR-3: What if an entry point has no outgoing CALLS edges?
- FR-4: What's the depth limit for impact analysis? Is there a max depth? What about cycles in the call graph?
- FR-5: What if git diff touches files not in the graph?
- FR-7: What if BM25 index and vector index return different result sets? How are empty results handled in fusion?
- NFR-1: "大规模仓库（~5000 文件）应在可接受范围内完成" - "可接受范围内" is not measurable. This is vague.

**Internal consistency:**
- FR-1 says "语言支持至少达到：TypeScript、JavaScript、Python、Go、Java、Rust（与 graphify 现有支持对齐，不引入新语言依赖）" - but section 2.6 and 2.1 don't explicitly list which languages graphify currently supports. The spec claims alignment with "graphify 现有支持" but doesn't cite the source.
- Section 3.2 says graphify's AST supports "主流语言（完整列表待确认）" - this is a self-acknowledged gap that contradicts the certainty of FR-1's language list.
- FR-2 mentions HERITAGE edges for class inheritance, but FR-1's symbol types don't include a "parent class" or "superclass" field on class nodes. How is the inheritance target resolved if it's defined in another file?
- Section 4.1 goal 5 says "补齐 context、impact、trace、detect_changes 等代码分析专用工具" but FR-6 lists exactly these four tools plus keeping existing ones. Consistent.
- AC-10 verifies "社区检测结果具有语义连贯性" but this is not a new requirement - community detection is an existing capability (section 2.2). This AC doesn't verify any new FR.
- The milestone table M3 lists "FR-3 执行流追踪 + FR-5 git-diff 影响映射" with priority P2. But FR-3 is P2 and FR-5 is P2. However, FR-5 depends on FR-3's process nodes (FR-5 says "返回受影响的执行流（process）列表"). So FR-3 and FR-5 are in the same milestone - is there an ordering within M3? Not specified.
- NFR-1 mentions "Process Detection" in the performance budget, but FR-3 is called "执行流追踪（Process Detection）". Consistent terminology.

Let me also check:
- FR-8 says "检测结果作为入口点评分的输入信号之一（FR-3）" but FR-3 is P2/M3 and FR-8 is P4/M5. FR-3's entry point scoring won't have framework detection until M5. The spec should acknowledge this phased dependency or specify what FR-3 uses before FR-8 is available.

**Acceptance criteria testability:**
- AC-8: "RRF 融合结果的召回率不低于纯向量搜索" - how is "召回率" (recall) measured? Against what ground truth? No test set is defined.
- AC-10: "社区划分应与代码的功能模块划分基本一致" - "基本一致" is subjective. What's the measurable criterion?
- NFR-1: "可接受范围内" for 5000 files is not measurable.
- No AC for NFR-1, NFR-2, NFR-3, NFR-5, NFR-6.

Let me also check if there's a missing FR for configuration parsing. Section 3.2 lists "配置解析" as a GitNexus capability that's "完全缺失" in graphify, but there's no FR to address this gap. The spec's goals (section 4.1) don't mention configuration parsing. Is this intentionally omitted? It's not listed in non-goals either. This is a gap in coverage - a identified gap with no corresponding requirement or explicit non-goal.

Similarly, "多仓库契约" (cross-repo contracts) is listed as "缺契约提取与注册" in section 3.2 but has no FR or explicit non-goal. "Wiki 生成" is listed as "部分覆盖，缺 LLM 文档生成" but has no FR. "Agent skills" is listed as "完全缺失" but is explicitly in non-goals (4.2.5). "Claude Code hooks" is "部分覆盖" but has no FR. "Cypher 查询" is listed as "缺交互式查询能力" but has no FR.

These are either intentional omissions (should be in non-goals) or gaps. The non-goals section only addresses: graph storage, PDG/taint analysis, multi-file rename, Web UI, Agent skills. Other gaps from section 3.2 are not addressed.

Let me now compile my findings:

1. **AC-1 doesn't cover all FR-1 symbol types** - FR-1 lists 7 symbol types but AC-1 only verifies 4. (major, traceability gap)

2. **Missing ACs for HERITAGE and DEFINES edges** - FR-2 defines 4 edge types but only CALLS (AC-2) and IMPORTS (AC-3) have acceptance criteria. (major, traceability gap)

3. **FR-8 has no acceptance criterion** - FR-8 (框架检测) is a P4 requirement but has no corresponding AC. (major, traceability gap)

4. **NFR-1 performance for 5000 files is not measurable** - "可接受范围内" is undefined. (major, testability)

5. **No ACs for NFR-1, NFR-2, NFR-3, NFR-5, NFR-6** - Multiple NFRs lack acceptance criteria. (major, traceability)

6. **AC-8 recall measurement undefined** - "召回率不低于纯向量搜索" doesn't define ground truth or measurement method. (major, testability)

7. **AC-10 is subjective** - "基本一致" is not measurable, and it verifies an existing capability, not a new requirement. (minor, testability)

8. **FR-2 edge schemas undefined** - CALLS, IMPORTS, HERITAGE, DEFINES edges lack formal schema definition (source/target node types, properties). (major, interface contract)

9. **FR-6 MCP tool input/output contracts undefined** - context, impact, trace, detect_changes tools have no parameter or response schema. (major, interface contract)

10. **FR-5 git-diff input format unspecified** - "接收 git diff" doesn't define the input format. (major, interface contract)

11. **FR-3 recursive call chain handling unspecified** - No mention of cycle detection or depth limits for call chain tracing. (major, boundary conditions)

12. **FR-4 depth limit and cycle handling unspecified** - Impact analysis doesn't define max depth or cycle handling. (major, boundary conditions)

13. **FR-3/FR-8 temporal dependency** - FR-3 (M3) depends on FR-8 (M5) for entry point scoring input, but FR-8 is delivered 2 milestones later. No interim behavior specified. (major, internal consistency)

14. **FR-1 language list claims alignment with graphify existing support, but section 3.2 admits "完整列表待确认"** - Contradiction between FR-1's certainty and section 3.2's uncertainty. (minor, internal consistency)

15. **Identified gaps from section 3.2 without corresponding FR or non-goal** - Configuration parsing, multi-repo contracts, wiki generation, interactive Cypher, Claude Code hooks are listed as gaps but have no FR or explicit non-goal. (minor, completeness)

16. **AC-10 verifies existing capability, not new requirement** - Community detection is existing (section 2.2), so AC-10 doesn't verify any new FR. (minor, traceability)

17. **FR-4 confidence scoring numeric values undefined** - Only qualitative mapping given, no actual confidence values. (minor, interface contract)

18. **FR-3 process node "调用链步骤列表" structure undefined** - What each step contains is not specified. (minor, interface contract)

Let me prioritize these and prepare the final verdict. 

Actually, let me reconsider the severity levels:
- The missing ACs for FR-8, HERITAGE/DEFINES edges, and multiple NFRs are major traceability issues
- The undefined interface contracts (edge schemas, MCP tool schemas, git-diff format) are major
- The boundary condition gaps (cycles, depth limits) are major
- The FR-3/FR-8 temporal dependency is a major consistency issue
- The NFR-1 vagueness and AC-8/AC-10 testability issues are major
- The minor issues are smaller inconsistencies

Overall severity: I'd say major, because while the spec has good structure and covers many aspects, there are significant gaps in traceability (missing ACs), interface contracts (undefined schemas), and boundary conditions.

Confidence: 0.88 - I'm fairly confident in my findings as they're based on direct evidence from the spec.

Let me structure the findings properly.

```json
{
  "severity": "major",
  "confidence": 0.88,
  "reasoning": "本规格文档结构完整，覆盖背景、对标分析、目标/非目标、8 条功能需求、6 条非功能需求、10 条验收标准与里程碑。但在 spec-reviewer 的五个审查维度（可追溯性、接口契约完整性、边界条件、验收标准可测试性、内部一致性）上均存在明确证据支撑的缺陷：(1) 可追溯性——FR-2 的 HERITAGE/DEFINES 边、FR-8 框架检测、NFR-1/2/3/5/6 均无对应验收标准；(2) 接口契约——多条边类型与 MCP 工具缺少 schema 定义、git-diff 输入格式未指定；(3) 边界条件——调用链与影响分析的循环/深度限制未覆盖；(4) 可测试性——AC-8 召回率无 ground truth、AC-10 '基本一致' 不可量化、NFR-1 '可接受范围' 不可测量；(5) 内部一致性——FR-3(M3) 依赖 FR-8(M5) 的框架检测作为入口点评分输入但未说明过渡行为。这些缺陷不致使规格无法实施，但会在实现与验收阶段引入歧义，综合判定为 major。",
  "findings": [
    {
      "description": "FR-2 定义了 4 种边类型（CALLS/IMPORTS/HERITAGE/DEFINES），但验收标准仅覆盖 CALLS（AC-2）和 IMPORTS（AC-3），HERITAGE 边和 DEFINES 边无对应验收标准，无法验证其正确性。",
      "severity": "major",
      "confidence": 0.95,
      "evidence": "FR-2 要求列表包含「继承边（HERITAGE）：类 → 父类/接口实现」和「定义边（DEFINES）：文件 → 其定义的符号」（第 228-229 行）。验收标准表中 AC-2 验证 CALLS 边（第 363 行）、AC-3 验证 IMPORTS 边（第 364 行），但无任何 AC 提及 HERITAGE 或 DEFINES。",
      "suggestion": "新增 AC 验证 HERITAGE 边（对包含类继承/接口实现的测试仓库验证继承关系连接正确）和 DEFINES 边（验证文件节点到其所定义符号节点的 DEFINES 边完整性）。"
    },
    {
      "description": "FR-8（框架检测与入口点配置，P4）没有任何对应的验收标准，无法验证框架检测的正确性与可扩展性。",
      "severity": "major",
      "confidence": 0.95,
      "evidence": "FR-8 在第 305-316 行定义，优先级 P4。验收标准表（第 360-371 行）从 AC-1 到 AC-10，无任何一条引用 FR-8 或提及框架检测。",
      "suggestion": "新增 AC：对包含已知框架模式（如 Express handler、FastAPI 路由）的测试仓库验证框架检测标记正确，且新增框架规则无需修改核心代码。"
    },
    {
      "description": "NFR-1（索引性能）、NFR-2（增量更新耗时）、NFR-3（存储占用）、NFR-5（确定性）、NFR-6（诚实性）均无对应验收标准。验收标准仅覆盖 NFR-4（AC-9），其余 5 条 NFR 缺乏可执行的验收方法。",
      "severity": "major",
      "confidence": 0.92,
      "evidence": "验收标准表（第 360-371 行）中 AC-9 验证 NFR-4 向后兼容，AC-10 验证社区检测（非任何 NFR）。NFR-1（第 323-327 行）、NFR-2（第 329-332 行）、NFR-3（第 334-337 行）、NFR-5（第 345-348 行）、NFR-6（第 351-354 行）均无对应 AC。",
      "suggestion": "为每条 NFR 新增验收标准：NFR-1 用计时测试验证 500 文件 ≤60s；NFR-2 验证增量更新不触发全量重建且 git-diff 映射秒级返回；NFR-3 验证 graph.json 增长 ≤3x；NFR-5 验证相同输入二次运行输出一致；NFR-6 验证未解析调用标注为 AMBIGUOUS 且健康检查覆盖新边类型。"
    },
    {
      "description": "FR-2 定义的 4 种边类型（CALLS/IMPORTS/HERITAGE/DEFINES）缺少形式化 schema 定义——未指定源节点类型、目标节点类型、边属性。例如 IMPORTS 边的源是「文件」节点还是「模块」节点？CALLS 边是否携带调用位置（行号）属性？HERITAGE 边如何区分继承与接口实现？",
      "severity": "major",
      "confidence": 0.85,
      "evidence": "FR-2 要求列表（第 224-229 行）仅给出边的自然语言描述：「调用边（CALLS）：函数/方法调用 → 被调用函数/方法」「继承边（HERITAGE）：类 → 父类/接口实现」「定义边（DEFINES）：文件 → 其定义的符号」，未定义边的形式化 schema（source_type, target_type, properties）。FR-1（第 215 行）定义了符号节点的属性（符号名、限定名、文件路径、起止行号、符号类别），但边无对应的属性定义。",
      "suggestion": "为每种边类型补充 schema 定义，至少包含：source_node_type、target_node_type、必选属性（如调用位置行号、继承类型 enum）、可选属性。可使用表格或 JSON Schema 形式。"
    },
    {
      "description": "FR-6 定义了 4 个新增 MCP 工具（context/impact/trace/detect_changes），但未定义任何工具的输入参数 schema 和输出响应 schema，接口契约不完整。",
      "severity": "major",
      "confidence": 0.85,
      "evidence": "FR-6（第 280-290 行）仅以自然语言描述各工具行为：「context：给定一个符号，返回其 360 度视图」「trace：两个符号之间的最短有向调用路径」。未定义输入参数（符号用什么标识？限定名？节点 ID？）、输出 JSON 结构、错误码或异常路径。AC-7（第 368 行）仅验证「可通过 stdio 调用」和「响应格式」，但响应格式本身未在 FR-6 中定义。",
      "suggestion": "为每个 MCP 工具补充接口契约：输入参数（名称、类型、必选/可选）、输出 schema（JSON 结构示例）、错误码与异常路径（如符号不存在时返回什么）。"
    },
    {
      "description": "FR-5 要求「接收 git diff（文件级 + 行级）」但未指定输入格式——是 unified diff 文本？结构化 JSON？还是调用者自行解析后传入行号范围？接口契约缺失。",
      "severity": "major",
      "confidence": 0.82,
      "evidence": "FR-5（第 270-275 行）写「接收 git diff（文件级 + 行级），映射到受影响的符号节点」和「支持作为 MCP 工具调用（detect_changes）」，但未定义 detect_changes 工具的输入参数类型与格式。",
      "suggestion": "明确 detect_changes 的输入格式：例如接收 unified diff 字符串或 {file, added_lines, removed_lines}[] 结构，并定义输出 schema（受影响符号列表 + process 列表）。"
    },
    {
      "description": "FR-3 执行流追踪未定义调用链的循环处理与深度限制。代码中常见的递归调用（A→B→A）和互相调用（A→B→A）会导致调用链追踪无限循环。",
      "severity": "major",
      "confidence": 0.80,
      "evidence": "FR-3（第 240-249 行）要求「沿 CALLS 边从入口点出发，构建有向调用子图，记录每一步的调用关系」和「process 节点应包含…调用链步骤列表」，但未提及循环检测、最大深度限制或已访问节点去重策略。",
      "suggestion": "补充边界条件：定义最大追踪深度（可配置）、循环检测策略（如已访问符号集去重，或标记为循环引用）、空调用链（入口点无 outgoing CALLS 边）的处理行为。"
    },
    {
      "description": "FR-4 影响分析未定义最大深度限制和循环处理。影响分析沿 CALLS 边传播，在有环调用图中会无限传播。",
      "severity": "major",
      "confidence": 0.80,
      "evidence": "FR-4（第 255-262 行）要求「下游影响：沿 CALLS 边方向…按调用深度分层」「上游影响：逆 CALLS 边方向…按深度分层」，但未定义最大深度上限、循环检测或深度无限制时的终止条件。",
      "suggestion": "补充边界条件：定义默认最大深度（可配置）、循环检测策略、以及当达到最大深度时的截断行为与提示。"
    },
    {
      "description": "FR-3（P2/M3）的入口点评分声称「可配置、可扩展」，FR-8（P4/M5）的框架检测结果作为 FR-3 入口点评分的输入信号。但 FR-8 在 M5 才交付，FR-3 在 M3 就需实现——FR-3 在 FR-8 可用前的入口点评分行为未定义，存在时序依赖不一致。",
      "severity": "major",
      "confidence": 0.78,
      "evidence": "FR-8（第 313 行）：「检测结果作为入口点评分的输入信号之一（FR-3）」。里程碑表（第 379-384 行）：M3 交付「FR-3 执行流追踪」，M5 交付「FR-8 框架检测，入口点评分完善」。FR-3 在 M3 实现时 FR-8 尚未存在，但规格未说明 M3-M4 阶段入口点评分在缺少框架检测信号时如何工作。",
      "suggestion": "明确分阶段行为：M3 阶段 FR-3 使用哪些入口点评分信号（如 main 函数、HTTP handler 模式），并说明 M5 引入框架检测后评分逻辑如何更新。或在 FR-3 中注明「框架检测信号在 FR-8 交付后接入，此前使用基础启发式」。"
    },
    {
      "description": "NFR-1 对大规模仓库（~5000 文件）的性能要求为「应在可接受范围内完成全量索引」，「可接受范围」未定义具体数值，不可测量、不可验收。",
      "severity": "major",
      "confidence": 0.90,
      "evidence": "NFR-1（第 327 行）：「大规模仓库（~5000 文件）应在可接受范围内完成全量索引」。对比第 325 行对中等规模仓库给出了明确数值（60 秒内），但大规模仓库无对应数值。",
      "suggestion": "为 5000 文件仓库设定具体时间上限（如 10 分钟内），或明确说明「可接受范围」的参考基准（如与 GitNexus 同等规模仓库的索引时间对比）。"
    },
    {
      "description": "AC-8 要求「RRF 融合结果的召回率不低于纯向量搜索」，但未定义召回率的测量方法与 ground truth 来源，验收标准不可执行。",
      "severity": "major",
      "confidence": 0.82,
      "evidence": "AC-8（第 369 行）：「对同一查询，RRF 融合结果的召回率不低于纯向量搜索」。未定义测试查询集、相关文档 ground truth 标注方法、召回率计算公式。",
      "suggestion": "定义测试集（如 N 个已知代码查询及其预期结果符号集）、召回率计算方法（如 |融合结果 ∩ ground_truth| / |ground_truth|），并设定最低召回率阈值。"
    },
    {
      "description": "FR-1 声称语言列表「与 graphify 现有支持对齐，不引入新语言依赖」，但第 3.2 节对标表中 graphify 现状写「支持主流语言（完整列表待确认）」，两处对 graphify 现有语言支持的确定性存在矛盾。",
      "severity": "minor",
      "confidence": 0.75,
      "evidence": "FR-1（第 213-214 行）：「语言支持至少达到：TypeScript、JavaScript、Python、Go、Java、Rust（与 graphify 现有支持对齐，不引入新语言依赖）」。第 3.2 节对标表（第 150 行）：graphify 现状为「AST 结构提取（Part A），支持主流语言（完整列表待确认）」。",
      "suggestion": "在第 2 节 graphify 现状中明确列出当前支持的语言列表，消除「待确认」的不确定性；或在 FR-1 中注明语言列表基于 graphify SKILL.md 实际定义并引用具体来源行。"
    },
    {
      "description": "AC-10 验证「社区检测结果具有语义连贯性」且判定方法为「社区划分应与代码的功能模块划分基本一致」，但社区检测是 graphify 现有能力（第 2.2 节），非本规格新增需求。该 AC 未验证任何新增 FR，且「基本一致」不可量化。",
      "severity": "minor",
      "confidence": 0.70,
      "evidence": "社区检测在第 2.2 节（第 80-81 行）列为现有能力。AC-10（第 371 行）：「对测试仓库，社区划分应与代码的功能模块划分基本一致」——「基本一致」无量化标准，且该 AC 不对应任何新增 FR（FR-1 至 FR-8 均未将社区检测增强列为需求）。",
      "suggestion": "要么将 AC-10 替换为验证新增需求的 AC（如 FR-8 框架检测），要么明确 AC-10 的目的是验证新增 CALLS/HERITAGE 边对社区检测质量的改善，并定义可量化的判定指标（如模块度 Q 值或人工标注一致率阈值）。"
    },
    {
      "description": "第 3.2 节对标表识别出多项 gap（配置解析、多仓库契约、Wiki 生成、交互式 Cypher、Claude Code hooks），这些 gap 既无对应 FR 也未列入非目标（第 4.2 节），需求覆盖边界不清晰。",
      "severity": "minor",
      "confidence": 0.72,
      "evidence": "第 3.2 节对标表（第 148-173 行）列出：配置解析「完全缺失」、多仓库契约「缺契约提取与注册」、Wiki 生成「缺 LLM 文档生成」、Cypher 查询「缺交互式查询能力」、Claude Code hooks「部分覆盖」。非目标（第 4.2 节，第 194-201 行）仅列出 5 项（图存储、PDG、重命名、Web UI、Agent skills），上述 gap 均未出现在目标或非目标中。",
      "suggestion": "在对标表后或非目标节中明确说明：这些 gap 是有意推迟到后续阶段还是视为超出范围。对每项 gap 标注「本期不覆盖」或「后续阶段考虑」，避免实现者对范围产生歧义。"
    },
    {
      "description": "FR-4 置信度评分仅给出定性映射（EXTRACTED 高/INFERRED 中/AMBIGUOUS 低），未定义具体数值或数值区间，实现者无法确定评分计算方式。",
      "severity": "minor",
      "confidence": 0.72,
      "evidence": "FR-4（第 260-261 行）：「评分基于边的来源（EXTRACTED 边高置信、INFERRED 边中置信、AMBIGUOUS 边低置信）」，示例为「[CALLS 90%]」。但未定义每种来源对应的数值或区间（如 EXTRACTED=90%、INFERRED=60%、AMBIGUOUS=30%），也未定义路径级别置信度的聚合方式（多条边组成的路径如何计算综合置信度）。",
      "suggestion": "定义每种边来源的置信度数值或区间，并说明路径级置信度的聚合公式（如取最小值、加权平均等）。"
    },
    {
      "description": "FR-3 中 process 节点要求包含「调用链步骤列表」，但未定义每个步骤的数据结构——步骤是符号引用？还是包含调用边和调用位置的复合结构？",
      "severity": "minor",
      "confidence": 0.70,
      "evidence": "FR-3（第 247 行）：「process 节点应包含：入口点符号、调用链步骤列表、覆盖的符号集合」。「调用链步骤列表」的结构未定义。",
      "suggestion": "定义调用链步骤的数据结构，如 {symbol: string, depth: int, edge_type: string, call_site_line: int}，并说明步骤顺序（DFS 序 vs BFS 序）。"
    },
    {
      "description": "AC-1 验证 FR-1「符号提取覆盖 6 种语言的函数/类/方法/接口」，但 FR-1 实际要求 7 种符号类型（函数、方法、类、接口、类型别名、变量声明、模块/命名空间），AC 仅覆盖其中 4 种，验收范围小于需求范围。",
      "severity": "minor",
      "confidence": 0.88,
      "evidence": "FR-1（第 212 行）：「符号类型至少覆盖：函数、方法、类、接口、类型别名、变量声明、模块/命名空间」（7 种）。AC-1（第 362 行）：「FR-1 符号提取覆盖 6 种语言的函数/类/方法/接口」（4 种符号类型）。",
      "suggestion": "将 AC-1 扩展为验证全部 7 种符号类型，或拆分为多条 AC 分别覆盖不同符号类型。"
    }
  ],
  "satisfied": false
}
```
