# 对抗审查系统规格说明书 (Spec)

---

## 1. 背景与动机

### 1.1 问题陈述

当前 AI Agent 在软件开发各环节(需求分析、规格定义、设计、实现、测试计划等)产出大量内容,但**单 Agent 不可靠**——存在幻觉、遗漏、自洽性偏差、过度自信等问题，人类逐项审查心智负担重。

### 1.2 核心立场

所有 AI 产出的东西都需要被另一个(组)AI **对抗审查**一遍。这不是代码 review(不审查代码风格、模式、性能),而是对 **AI 产出物本身的可靠性**进行多视角、可对抗、可量化的审计。

### 1.3 为什么需要独立系统

- 现有工具(Claude Code、Codex 等)内置的 review 能力是**单 agent、单视角**的,不可靠
- 需要一个**通用、可配置、可对抗**的审查层,横跨 AI 介入的所有环节
- 审查结果本身也是 AI 产出,**同样不可靠**,需要可被再次审查(元审查)

---

## 2. 审查范围

本系统审查的是 **AI 在软件开发各环节的产出物**,不限于也不特指代码。审查范围按软件开发管线分两大阶段组,每组覆盖多个子环节的产出物:

### 2.1 需求分析各环节

| 子阶段 | 产出物 | 审查焦点(非 code review) |
|---|---|---|
| 需求收集 | 原始需求列表 | 完整性(是否遗漏干系人需求)、来源可追溯 |
| 需求澄清 | 澄清后需求文档 | 歧义是否消除、假设是否记录 |
| 需求分解 | 需求层次结构 | 分解粒度是否合理、MECE 性 |
| 需求优先级 | 优先级排序 | 排序依据是否充分、MoSCoW 合理性 |
| 需求验收标准 | 验收标准清单 | 可测试性、完整性 |
| 规格文档(spec) | 规格文档 | 需求→规格可追溯性、接口契约完整性、边界条件覆盖、验收标准可测试性 |
| 设计文档 | 设计文档 | 设计是否覆盖所有需求、技术风险是否消解、方案选择是否有依据 |

### 2.2 代码生成后各环节

| 子阶段 | 产出物 | 审查焦点(非 code review) |
|---|---|---|
| 实现对照规格 | 代码 vs spec 对照 | 需求覆盖度、逻辑一致性、边界处理 |
| 单元测试 | 测试代码 | 是否覆盖需求路径、边界场景、断言有效性 |
| 集成测试 | 集成测试方案 | 接口契约验证、场景覆盖 |
| 部署配置 | Dockerfile/IaC | 配置与需求一致性、安全基线 |
| 文档 | API 文档/README | 与实现一致性、可读性 |
| 测试计划 | 测试计划文档 | 是否覆盖每条需求、负面场景是否齐、验收标准是否可执行 |

> **注**: "AI 生成的代码"的审查焦点是 **实现是否满足需求/规格**(非代码质量)——需求覆盖度、逻辑一致性、边界处理。本系统**不做**代码风格、命名规范、设计模式、性能微优化等传统 code review 工作(见 2.4 明确排除)。

### 2.3 外部代码检视产物的审查

代码检视(code review)本身**不在本系统职责内**,但外部代码检视工具(如 SonarQube、ESLint、人工 PR review)的**产物**可以作为本系统的输入被审查,判断检视报告本身是否可靠:

| 产出物 | 审查焦点 |
|---|---|
| 外部代码检视报告 | 检视是否覆盖需求关键模块、是否误报/漏报、severity 评定是否合理、修复建议是否可执行 |

### 2.4 明确排除

本系统**不做**以下审查:
- 代码风格、命名规范、格式化
- 设计模式选型、架构美学
- 性能微优化建议
- 这些属于传统 code review 范畴,由其他工具(SonarQube/ESLint/人工)处理。本系统可审查这些工具的**产物**,但不替代它们。

### 2.5 元审查(审查结果的审查)

审查者本身也是 AI,同样不可靠。因此系统输出的审查结果(`Verdict`)必须能作为输入,被另一组审查者(包括多个 `meta-reviewer`,使用不同模型/视角以形成真正对抗)再次审查。元审查的核心价值不只是"再查一遍",而是**校准原始审查的置信度**——如果元审查判定原始 confidence 失准,最终用于"是否升级人工"判定的是校准后的值(`calibrated_confidence`)。校准必须通过显式公式实现(非简单覆盖),详见 [design.md](./design.md) 5.4 节。

---

## 3. 功能性需求

### FR-1: 多阶段通用审查

系统必须能在 AI 介入的任意环节进行审查,通过外部配置定义各阶段的审查维度,而非硬编码特定阶段。审查范围覆盖 2.1(需求分析各子阶段)、2.2(代码生成后各子阶段)、2.3(外部代码检视产物)三组场景。

- 输入是任意文本(需求文档/规格/代码/审查报告等)
- 不依赖文件系统路径或特定数据结构(如 workspace、trajectory)
- 同一系统支持上述所有审查范围,通过切换 reviewer 配置实现
- 每个子阶段有对应的示例 reviewer YAML(见 `reviewers/` 目录)

### FR-2: 多 Agent 对抗审查策略

系统必须支持以下审查策略(前两项为核心,后两项为补充):

| 策略 | 描述 | 状态 |
|---|---|---|
| **多 agent 辩论** | N 个 reviewer 独立评审 → 1-3 轮对抗辩论(互相挑战) → 盲评终判 → 裁决合成 | 核心 |
| **交叉审查** | 一个 reviewer 审查另一个 reviewer 的判断(元审查的一种形式) | 核心 |
| **多模型配置** | 不同 reviewer 可指定不同 LLM 模型(如 Claude sonnet + Claude opus + GPT-4o),避免同模型共享盲区 | 核心 |
| **多数投票** | 同一 reviewer 配置内,同一模型调用 N 次后投票聚合(复用原始 AaaJ `DevAsk.check()` 的 `majority_vote` + `satisfied_ratio` + `confidence` 算法),作为辩论的轻量级反幻觉手段 | 正式策略(保留自 AaaJ) |

辩论阶段须满足:
- Phase 1(独立评审)各 reviewer **并行执行**,非串行
- 当 reviewer 数 < 2 时,跳过辩论阶段(单 reviewer 自说自话无对抗价值)
- **单 reviewer 快检形态下跳过盲评终判**(复核者=初判者,自检无增量价值;抗随机用 reviewer 模板的 `majority_vote` 多次独立采样,优于自我反思);`stability_score` 标记 `degraded=true`
- 辩论轮次后计算 **stability score**(多轮辩论后观点稳定性),作为共识可信度的辅助指标

**流程决策自动化**(三层模型,见 design.md 4.8):
- **L1 入口路由(默认 auto)**:零参数调用时,一次轻量 LLM 分类(temperature=0,可审计)自动判定内容类型与复杂度,选定档位(fast/standard/thorough)与 reviewer 组合——对标 LangGraph supervisor 路由 + CyberAgent 零参数体验
- **L0 规则自动(流程主体)**:全部流程跳过/短路由确定性代码规则决定(reviewer 计数/预算数字/置信度阈值比较),可复现;LLM 对流程主体零决定权
- **L2 人工覆盖(可选)**:`--profile fast/standard/thorough` 半决策,或细粒度参数全决策;显式参数覆盖 auto 路由
- 路由结果(档位/reviewer 组合/理由)完整记录于 JSON verdict 的 `route` 字段,可追溯

### FR-3: Claude 作为默认 LLM 后端

系统默认使用 Claude(Anthropic)作为 LLM 后端,同时支持多模型混用以避免同模型共享盲区。

- **默认模型**:通过 `litellm` 调用 `anthropic/claude-*` 模型(CLI `--model` 参数默认值)
- **per-reviewer 覆盖**:reviewer YAML 可指定不同模型(如 Claude opus、GPT-4o),实现异构模型交叉验证(FR-2)
- 不绑死单一供应商:默认是 Claude,但 reviewer 级别允许使用其他模型以形成交叉验证
- **凭证继承(宿主会话)**: 系统作为被编码 agent 调用的质量关卡,LLM 凭证默认从宿主会话环境继承而非要求独立 API key。Claude Code: `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` / `CLAUDE_CODE_OAUTH_TOKEN`(setup-token)自动继承,订阅登录凭证不可继承;OpenCode: 经本地网关(`--base-url`/`opencode-llm-proxy`)或启动 shell 显式 export。解析顺序:显式参数 > 环境变量 > litellm 内部回退
- **不支持**作为 Claude Code skill 在会话内触发(见 design.md 1.5 节:仅 CLI 管道方式)

### FR-4: 置信度评分与人工升级

系统必须对每条审查发现和整体裁决给出量化置信度,并基于阈值决定是否升级人工审查。

- 每条 finding 包含 `confidence: float (0.0-1.0)`
- 整体 Verdict 包含聚合后的 `confidence`
- 可配置阈值(默认 0.8):**置信度低于阈值的标记 `escalate_to_human: true`**
- 经过元审查的,使用**校准后的 confidence**(`calibrated_confidence`)作为升级判定依据
- 置信度通过 **Pydantic schema 强制结构化输出**(借鉴 LangGraph `with_structured_output(Pydantic)` 模式),而非依赖 LLM 自由文本解析。解析层须提供多级降级(JSON 代码块 → 裸 JSON → `<SATISFIED>` 标签),确保鲁棒性
- **`severity` 字段使用枚举类型**(非裸字符串),避免字符串字典序比较导致的"最严判定"逻辑错误

### FR-5: 独立 CLI

系统必须可作为独立 CLI 运行。

- CLI 支持三种输入:直接文本(`--content`)、文件(`--file`)、stdin 管道
- `--file` 支持 `.json` 后缀:当传入 JSON verdict 文件时,自动提取 verdict 文本作为审查内容(支持元审查场景)
- **零参数即全自动**:`aj review --file x.md` 不带任何流程参数时走 auto 路由(FR-2 三层决策模型),全程用户零决策;`--profile fast/standard/thorough` 显式选档;细粒度参数(`-r`/`--debate-rounds`/`--meta-review`)覆盖路由
- 不依赖特定 agent 运行时(不绑 Claude Code session、不绑 LangGraph Platform)
- **`--interactive` 模式**(借鉴 LangGraph `interrupt()` 概念,但不使用 Pregel/checkpointer):当审查置信度低于阈值时,CLI 暂停等待 stdin 人工裁决输入,而非直接输出 `escalate_to_human`。适用于人工在环场景;非 interactive 模式直接标注升级标记
- **不支持**作为 Python 库嵌入 agent 运行时——对外只暴露 CLI 管道方式,避免耦合(见 design.md 1.5 节)

### FR-6: 外部定义审查 Agent

审查者(reviewer)必须可通过外部配置文件定义,无需改代码。

- 配置格式:YAML(`*.yaml` 或 `*.yml`)
- 每个 reviewer 定义:名称、描述、模型(**可选**,不指定时用 CLI `--model` 默认值)、system prompt、检查清单(checklist)、权重、`majority_vote`(同模型多次调用投票数,默认 1)
- 系统从指定目录加载所有 reviewer 配置
- **约束模型**(匿名槽位 + 模板注入): 系统提供匿名的辩论 reviewer 槽位(行为框架固定),用户模板只注入"审查视角"(persona + checklist),**不能自定义辩论行为、输出格式、流程编排**——这些由系统固定控制(见 design.md 1.6 节)
- 用户可自定义任意审查视角模板(如 `security-auditor`、`compliance-reviewer`)
- **外部审查 skill(知识注入型)**: 用户可通过 SKILL.md 格式(Markdown + YAML frontmatter,兼容业界 skill 约定)定义审查知识包,由通用匿名 agent 槽位加载。两种方式: ① reviewer 模板通过 `skills: [name]` 字段引用(skill 正文注入 persona);② CLI `-r skill:<name>` 即席加载(匿名槽位直接以 skill 为完整审查视角)。skill 为纯 LLM 知识包(无工具执行),与纯 LLM 审查范式一致(见 design.md 1.6.4);工具型 skill 明确不支持
- reviewer 的 `model` 为可选字段,实现"全局默认 + per-reviewer 覆盖"的灵活配置;CLI `--override-model` 可强制覆盖所有 reviewer 的 model(用于"全用某模型测试"场景)
- 系统内置过程级审查模板(借鉴 CyberAgent 6 轴): 过程合规(process-compliance)/欺骗检测(deception-detector)/危险操作扫描(dangerous-operation-scanner),用户传入 agent 执行日志时选择性启用

### FR-7: 提示词传递审查内容

被审查的内容通过 prompt 流入系统,而非依赖特定数据结构或文件路径解析。

- `DebateOrchestrator.run(content: str, ...)` 接受任意文本
- reviewer 的 system prompt + user prompt 组合传递被审查内容
- 元审查时,上一轮的 `Verdict` 序列化为文本后作为 `content` 传入

### FR-8: 元审查(审查结果可被审查)

系统必须支持对自身输出的审查结果进行再次审查。

- `meta-reviewer` 配置定义元审查维度(漏判/过判/置信度失准/推理缺口/共识假象)
- 元审查须包含**完整性审计**(借鉴 agent-review-panel):检查原始审查是否覆盖了被审查内容的所有关键维度
- 元审查须使用**至少 2 个 meta-reviewer**(不同模型或不同 persona),形成真正对抗;单 reviewer 无法形成辩论对抗,会退化为自说自话
- **校准必须通过显式公式实现**(非简单覆盖元审查者自身的 confidence),详见 [design.md](./design.md) 5.4 节
- CLI 支持 `--meta-review` 开关和 `--review-depth N` 参数(默认 0 = 不元审查;`--meta-review` 等价于 `--review-depth 1`)
- 元审查输出校准后的 `calibrated_confidence`
- 防止无限递归:`--review-depth` 硬上限为 2(超过报错)

### FR-9: 双格式输出

每次审查必须输出两种格式:

| 格式 | 用途 | 输出方式 |
|---|---|---|
| **Markdown 报告** | 人类阅读——含各 reviewer 发现、辩论摘要、最终裁决、置信度、升级标记 | stdout(默认)或 `--output-dir` 指定目录写文件 |
| **JSON Verdict** | 机器消费——可被下游(元审查 / CI/CD / 反馈循环)程序化处理 | stdout(当 `--output json`)或写文件(当 `--output both --output-dir ./reports`) |

> **输出语义**:`--output markdown` → Markdown 到 stdout;`--output json` → JSON 到 stdout;`--output both` → 写两个文件(`report.md` + `verdict.json`)到 `--output-dir` 指定目录。JSON **不输出到 stderr**(stderr 仅供日志/进度,避免管道冲突)。

---

## 4. 非功能性需求

### NFR-1: 依赖精简

剥离原基座(agent-as-a-judge)的重型依赖(spacy、sentence-transformers、opencv、tree-siter 等),这些是代码证据收集用的,通用审查场景不需要。

### NFR-2: 成本可控

- 辩论轮次可配置(默认 2),支持 `--max-cost` 预算控制
- LLM broker 记录累计 token/cost,超限终止并报错
- 支持轻量模式(`--debate-rounds 0` = 仅独立评审无辩论)
- 支持 `--override-model` 切换到更便宜的模型进行测试

### NFR-3: 可追溯

- 每条 finding 必须引用被审查内容的具体依据(evidence)
- 辩论过程完整记录(各轮论点)
- 成本/时间/token 记录(写入 JSON verdict 的 `cost` 字段)

### NFR-4: 性能——独立评审并行执行

- Phase 1(独立评审)各 reviewer **并行执行**(用 `ThreadPoolExecutor` 或 `asyncio`),而非串行
- N 个 reviewer 的独立评审耗时 ≈ max(单次延迟),而非 sum(单次延迟)
- 借鉴 LangGraph 图原语天然支持并行的设计理念

### NFR-5: 辩论稳定性度量

- 多轮辩论后计算 **stability score**(观点稳定性):若 reviewer 在多轮辩论中立场未翻转,稳定性高;若频繁翻转,共识可信度低
- stability score 作为 `consensus_score` 的辅助指标写入 JSON 输出

### NFR-6: 开源合规

基座选 MIT 许可的组件,改造后系统可自由使用和分发。

---

## 5. 选型调研结论

### 5.1 调研范围

| 候选 | 来源 |
|---|---|
| `metauto-ai/agent-as-a-judge` | GitHub, ICML 2025, Python, litellm, MIT |
| CyberAgent agent-as-a-judge 集成 | CyberAgent 开发者博客(2026-06), Claude Code skill |
| LangGraph oversight/guardian | langchain-ai/langgraph + langgraph-supervisor-py |
| `okuuva/agent-review-panel` | GitHub, Claude Code plugin, 多 agent 辩论 |

### 5.2 对照结论

| 需求 | AaaJ | CyberAgent | LangGraph | agent-review-panel |
|---|---|---|---|---|
| 多阶段通用审查 | ⚠️ | ❌ | ✅ | ⚠️ |
| 多agent辩论 | ❌ | ❌ | ❌ | ✅ |
| 交叉审查 | ❌ | ❌ | ❌ | ✅ |
| 多模型配置 | ❌ | ❌ | ✅ | ❌ |
| Claude后端 | ✅ | ✅ | ✅ | ✅ |
| 置信度+升级 | ⚠️ | ❌ | ⚠️ | ✅ |
| 独立CLI/库 | ⚠️ | ❌ | ✅ | ❌ |
| 通用性 | ❌ | ❌ | ✅ | ⚠️ |
| 外部定义agent | ❌ | ❌ | ✅ | ⚠️ |
| 提示词传递 | ✅ | ✅ | ✅ | ✅ |
| 元审查 | ❌ | ❌ | ❌ | ❌ |

(✅=2, ⚠️=1, ❌=0;得分:AaaJ=11, CyberAgent=5, LangGraph=13, agent-review-panel=12)

### 5.3 基座选择:`metauto-ai/agent-as-a-judge`(fork 改造)

**选择理由(非得分最高,而是改造成本最低)**:

AaaJ 已解决三件最难的事:
1. 多轮投票聚合算法(`DevAsk.check()` 的 majority_vote + satisfied_ratio)
2. 置信度计算公式(`confidence = max(satisfied_ratio, 1 - satisfied_ratio)`)
3. judge prompt 工程模板

这些在 LangGraph 上都要从零写。AaaJ 的短板(无辩论、绑 benchmark、无多模型、无升级路由)可通过**剥离 + 扩展**解决;LangGraph 的短板(无审查语义)只能**从零构建**。剥离比构建快。

**不选 LangGraph 的关键原因**:
- `interrupt()` 绑定 Pregel + checkpointer,对 CLI 是负担(本场景不需要跨会话暂停/恢复)
- `langgraph-supervisor` 已软弃用(README 明确推荐手动 handoff 替代)
- 审查语义(辩论拓扑、置信度 schema、评分 prompt、升级路由)全需自建(~500-1000 LOC)

**从其他候选借鉴(不作为基座,只偷模式)**:
- CyberAgent:Stop-hook 自动触发、主动验证(judge 跑工具验证 claim)、双输出(Markdown + JSON with suggested_action)
- agent-review-panel:多 reviewer 辩论(1-3 轮)+ 盲评终判 + **完整性审计** + 多轮合并协议
- LangGraph:`with_structured_output(Pydantic)` 强制结构化置信度输出;图原语天然并行(独立评审阶段并行执行);`interrupt()` 人工介入概念(本系统用 `--interactive` stdin 实现,不使用 Pregel/checkpointer)

详细方案见 [design.md](./design.md)。

---

## 6. 术语表

| 术语 | 含义 |
|---|---|
| **reviewer** | 审查者,由 YAML 配置定义的角色化审查 agent |
| **Severity** | 严重程度枚举(`critical` / `major` / `minor` / `pass`),使用 `StrEnum` 实现,定义显式排序 `critical > major > minor > pass`,避免字符串字典序比较错误 |
| **Verdict** | 审查裁决,系统的核心输出数据结构 |
| **finding** | 单条审查发现(含 severity / confidence / evidence / suggestion) |
| **DebateOrchestrator** | 辩论编排器,管理多 reviewer 的独立评审→辩论→盲评→合成流程 |
| **consensus_score** | 共识度,反映 reviewer 之间在 satisfied 判定上的一致程度(0.0 = 完全分歧,1.0 = 完全一致),非聚合置信度 |
| **stability_score** | 稳定性,多轮辩论后 reviewer 观点的稳定程度(立场未翻转 = 高稳定),作为共识可信度的辅助指标 |
| **majority_vote** | 多数投票,同一 reviewer 配置内同一模型调用 N 次后投票聚合,复用自 AaaJ `DevAsk.check()` 算法,作为轻量级反幻觉手段 |
| **元审查 (meta-review)** | 对审查结果本身的再次审查,须使用至少 2 个 meta-reviewer 形成对抗 |
| **calibrated_confidence** | 元审查通过显式校准公式修正后的置信度,用于最终升级判定(非简单覆盖) |
| **escalate_to_human** | 置信度低于阈值时标记,表示需要人工介入 |
| **LLMBroker** | 多模型管理器,支持 per-reviewer 指定不同模型 + 实例缓存 + 累计成本/token 追踪 |
| **skill (审查 skill)** | 用户自定义的审查知识/指令包(SKILL.md 格式: Markdown 正文 + YAML frontmatter),由匿名 reviewer 槽位加载。知识注入型,不含工具执行;可被 reviewer 模板引用或 `-r skill:<name>` 即席加载 |
