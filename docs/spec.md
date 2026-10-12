# 对抗审查系统规格说明书 (Spec)

---

## 1. 背景与动机

### 1.1 问题陈述

当前 AI Agent 在软件开发各环节(需求分析、规格定义、设计、实现、测试计划等)产出大量内容,但**单 Agent 不可靠**——存在幻觉、遗漏、自洽性偏差、过度自信等问题,人类逐项审查心智负担重。

### 1.2 核心立场

所有 AI 产出的东西都需要被另一个(组)AI **对抗审查**一遍。这不是代码 review(不审查代码风格、模式、性能),而是对 **AI 产出物本身的可靠性**进行多视角、可对抗、可量化的审计。

### 1.3 宿主集成立场

系统以**宿主 agent 生态成员**形态交付:入口为宿主内 `judge-manager` 实体 Agent,reviewer 为宿主实体 Agent,LLM 能力(模型/凭证/额度)全部来自宿主已有配置——用户零模型配置。主路径对宿主的依赖仅限三项公共能力(Agent 定义文件 / 原生 subagent 拉起 / shell),**不引入宿主专有的 headless CLI**(详见 FR-3/FR-5/FR-10/FR-11 与 NFR-7)。

---

## 2. 审查范围

本系统审查的是 **AI 在软件开发各环节的产出物**,不限于也不特指代码。审查范围按软件开发管线分两大阶段组,每组覆盖多个子环节的产出物:

### 2.1 需求分析与设计阶段

| 产出物 | 审查焦点(非 code review) |
|---|---|
| 规格文档(spec) | 需求→规格可追溯性、接口契约完整性、边界条件覆盖、验收标准可测试性、歧义消除(模糊词已量化)、关键假设已记录、需求分解 MECE 性、非功能需求可量化 |
| 设计文档 | 设计是否覆盖所有需求(含非功能需求)、技术风险是否消解、方案选择是否有对比依据、组件接口与数据流自洽、失败模式与异常路径有设计 |

> **注**:需求收集(原始输入)、需求澄清、需求分解、需求优先级排序是需求分析**过程中的活动**,产出物最终合入规格文档。本系统审查的是**产出物**(规格文档/设计文档),不审查分析过程。spec-reviewer 的 checklist 已覆盖歧义消除、MECE 分解、验收标准可测试性等维度。

### 2.2 代码生成后各阶段产出物

| 产出物 | 审查焦点(非 code review) |
|---|---|
| 实现代码 vs spec 对照 | 需求覆盖度、逻辑一致性、边界处理 |
| 单元测试代码 | 断言有效性(非"不抛异常")、需求路径覆盖、mock 合理性、测试独立性 |
| 集成测试方案/代码 | 接口契约验证(含错误分支)、超时/重试/幂等验证、环境策略 |
| 部署配置(Dockerfile/IaC) | 配置与需求一致性、安全基线(非 root、版本标签、secret 管理) |
| API 文档/README | 与实现一致性、示例可运行性、参数/错误码完整性 |
| 测试计划文档 | 是否覆盖每条需求、负面场景齐备、验收标准可执行 |

> **注**:上述各产出物是代码生成后**不同类型的文件**,由不同 reviewer 模板审查。其中**实现对照规格**是核心(审查代码是否满足需求),其余审查的是各自的产出物质量(测试代码审查测试有效性,部署配置审查安全基线,文档审查一致性)。用户传入不同文件时,引擎按 `--scene` 路由到匹配的 reviewer。

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

## 3. 对外竞争力关键技术点

| # | 技术点 | 说明 |
|---|---|---|
| 1 | **多 agent 辩论式审查** | 4 阶段流程(独立评审→对抗辩论→盲评终判→裁决合成),reviewer 之间互相挑战而非各自孤立判断,避免单 agent 的过度自信 |
| 2 | **异构 reviewer 面板** | 不同角色不同模型(如 Claude sonnet + opus + GPT-4o)形成对抗,避免同模型共享盲区。模型配置写在 reviewer 定义的 frontmatter 中 |
| 3 | **渐进式门控** | 哨兵先行 + 结果驱动门控,零 LLM 预分类。流程强度由 Phase 1 实测信号(severity/confidence/共识)决定,而非入口处的复杂度预测 |
| 4 | **元审查 + 显式校准公式** | 审查结果本身可被审查。至少 2 个 meta-reviewer 对抗审查,通过显式公式校准置信度,而非简单覆盖 |
| 5 | **置信度驱动人工升级** | 每条 finding 和整体 verdict 都有量化置信度,低于阈值自动标记 `escalate_to_human` |
| 6 | **外部定义 reviewer + skill 知识包** | reviewer 用 Markdown frontmatter + persona 正文定义,skill 用 SKILL.md 格式定义,均无需改代码。匿名槽位 + 视角注入约束模型 |
| 7 | **宿主零配置** | judge-manager Agent + 实体 reviewer Agent,LLM 模型/凭证/额度全部来自宿主已有配置,用户零模型配置、零 API key |
| 8 | **自身可递归审查** | Verdict 序列化为文本后可作为输入再次审查,`--review-depth` 控制递归深度(硬上限 2) |
| 9 | **通用管道接入** | 任意文本产出物,三种输入方式(`--content` / `--file` / stdin 管道)。不依赖文件系统路径或特定数据结构 |
| 10 | **纯 LLM 范式 + 可选证据注入** | 轻依赖(litellm/pydantic/typer/yaml),不绑代码 workspace。reviewer 不执行工具,但审查代码产出物时可通过 graphify 图谱证据注入获得代码结构上下文。graphify 不存在时静默降级为纯 LLM 模式 |
| 11 | **主动验证(graphify 证据注入)** | 审查代码产出物时,引擎在调 reviewer 前自动从本地 graphify 知识图谱收集代码结构证据(调用链、依赖关系、跨文件引用),注入 reviewer prompt 的 context 部分。reviewer 仍为纯 LLM,但 prompt 里多了代码结构证据,能验证 finding 是否与代码实际结构一致。替代 AaaJ 的 tree-sitter/BM25/embedding 工具层,无需自建 |
| 12 | **辩论溯源标记(错误级联防御)** | Phase 2 对抗辩论中,每条引用他人主张须标注认知状态三态标记:`[✓已确认]`/`[✗已反驳]`/`[?未验证]`。不带标记的引用视为无效反驳;`[?未验证]`主张不得作为调整 severity/confidence 的依据。conformity 检测在 Phase 3 检查是否有人基于未验证主张改变了立场。防御"一条幻觉主张在 3 轮内感染全部 reviewer"的级联风险 |
| 13 | **推理策略多样性** | 每个 reviewer 模板在 frontmatter 声明 `reasoning_strategy`(checklist/inverse/transform/counterfactual/falsification),系统在 system prompt 中注入对应推理策略指引。引擎的 `deterministic_panel` 贪心选择确保面板内至少 2 种不同推理策略。打破"所有 reviewer 共享同一推理范式、共享同一盲区"的问题(DMAD, ICLR 2025) |
| 14 | **自动辩论强度(auto agreement intensity)** | Phase 2 辩论的质疑强度由 Phase 1 实测信号自动推断:发现 critical 或 reviewer 严重分歧 → 高质疑(0.9);全员一致且仅 minor → 低质疑(0.4)快速收敛;其余 → 中等(0.7)。零外部配置,用户无需调参 |
| 15 | **三级行动决策(green/yellow/red)** | Verdict 输出三级行动决策:`green`(置信度 ≥ 0.9 且 severity ≤ minor 且全部 finding 有修复建议 → AI 可自行修复)、`yellow`(置信度足够但存在 major 问题 → 需人工确认修复方案)、`red`(置信度不足或 critical → 必须人工介入)。judge-manager 按级别分级汇报,人工介入时提供完整审查报告+元审查校准结果+流程审计信息 |

---

## 4. 核心审查流程（外部视角）

### 4.1 零参数 auto 流程

零参数调用时,系统不做先验复杂度分类,而是**哨兵先行 + 结果驱动门控**:

1. **起跑**:对全文做 token 计数。短内容(< 8000 token)派 1 名哨兵先行;长内容直接派 3 人面板
2. **哨兵独立评审**:哨兵 reviewer 独立审查,产出第一份 verdict
3. **门 1(早停判定)**:如果哨兵未发现 major 及以上问题且置信度足够高(≥ 0.9),判定为"简单",直接合成输出,结束。否则进入下一步
4. **面板扩张**:哨兵 verdict 保留(不重复计算),补足到 3 人并行独立评审
5. **门 2(续跑强度)**:根据实测信号选择续跑强度。发现 critical 问题或加权置信度偏低 → thorough 续跑(2 轮辩论 + 盲评终判 + 元审查);其余 → standard 续跑(1 轮辩论 + 盲评终判)
6. **终态**:按选定强度完成 4 阶段辩论,产出 verdict 和报告

整个路径(token 数 / 早停标记 / 门控理由 / 最终 reviewer 组合)完整记录在 JSON verdict 的 `route` 字段中,可追溯可复盘。

### 4.2 三档 Profile

| 档位 | reviewer 数 | 辩论轮 | 元审查 | LLM 调用数 | 适用场景 |
|---|---|---|---|---|---|
| **fast** | 1 | 0 | 否 | 1 | 短文本快检、CI 门禁、迭代内自检 |
| **standard** | 2 | 1 | 否 | ~6 | 常规文档审查 |
| **thorough** | 3 | 2 | 是 | ~15 | 关键交付物、终审 |

零参数时 auto 流程自动选档;显式 `--profile` 跳过渐进式;细粒度参数(`-r`/`--debate-rounds`/`--meta-review`)跳过渐进式,按指定参数执行。

### 4.3 4 阶段辩论流程

- **Phase 1 独立评审(并行)**:N 个 reviewer 各自独立审查被审查内容,互不知晓彼此判断。各 reviewer 并行执行,耗时约等于单次延迟而非 N 倍。当 reviewer 数 < 2 时跳过后续辩论阶段
- **Phase 2 对抗辩论**:各 reviewer 看到其他人的观点后进行反驳。1-3 轮,每轮前检查预算。单 reviewer 快检形态跳过此阶段
- **Phase 3 盲评终判(并行)**:辩论结束后,各 reviewer 独立给出最终裁决。单 reviewer 快检形态跳过此阶段(复核者=初判者,自检无增量价值)
- **Phase 4 裁决合成**:加权聚合各 reviewer 终判。整体 severity 取最严判定(critical > major > minor > pass,显式排序),置信度按 reviewer 权重加权平均。计算 consensus_score(reviewer 间一致度)和 stability_score(辩论前后立场稳定性)

### 4.4 元审查流程

1. **Verdict 序列化**:原始审查的 Verdict 被序列化为文本,作为元审查的输入内容
2. **多 meta-reviewer 对抗**:至少 2 个 meta-reviewer(不同模型/视角)对原始审查报告进行审查,维度包括漏判、过判、置信度失准、推理缺口、共识假象、完整性审计
3. **显式校准公式**:`calibrated = original_confidence × (1 - meta_penalty)`,其中 meta_penalty 根据元审查发现的最严重 severity 计算(critical=0.5, major=0.3, minor=0.1, pass=0.0)。若元审查者给出显式调整量,则加权融合
4. **升级判定**:使用校准后的 `calibrated_confidence`(而非原始 confidence)作为是否升级人工的判定依据

### 4.5 输出格式

每次审查输出两种格式:Markdown 报告(人类阅读)和 JSON Verdict(机器消费)。

JSON Verdict 核心字段:

```json
{
  "verdict": {
    "severity": "major",
    "confidence": 0.65,
    "calibrated_confidence": 0.455,
    "escalate_to_human": true,
    "auto_fix_eligible": false,
    "action_level": "red",
    "action_reasoning": "置信度 0.46 < 阈值 0.8,需人工介入",
    "findings": [
      {"description": "...", "severity": "major", "confidence": 0.72,
       "evidence": "原文引用", "suggestion": "改进建议"}
    ]
  },
  "route": {"profile": "standard", "reviewer_names": ["..."], "reason": "..."},
  "consensus_score": 0.75,
  "stability_score": 1.0,
  "meta_review": {},
  "cost": {"total_tokens": 15420, "total_cost_usd": 0.12}
}
```

### 4.6 主动验证（graphify 证据注入）

审查代码产出物时,引擎在调 reviewer 之前自动尝试从本地 graphify 知识图谱收集代码结构证据,注入 reviewer prompt 的 context 部分。这是**证据注入**,不是工具执行:reviewer 仍然不执行工具,仍然是纯 LLM 调用,但 prompt 里多了代码结构证据(调用链、依赖关系、跨文件引用),reviewer 能据此验证 finding 是否与代码实际结构一致。

**触发条件**(全部满足才收集证据):
1. graphify CLI 在 PATH 中可用
2. 当前工作目录下存在 `.graph/graph.json` 图谱文件
3. 被审查内容看起来像代码(文件名有代码后缀如 .py/.ts/.go/.rs,或内容含 def/class/function/import 等关键字)

**不满足时静默跳过**,降级为纯 LLM 模式(无证据注入),reviewer 只基于被审查文本判断。用户无感知,无需配置。

**收集方式**:引擎调 `graphify query` 和 `graphify explain` CLI 命令,查询与被审查内容相关的节点和调用关系。输出是纯文本,直接拼装到 reviewer prompt 的 `# 背景上下文` 部分。

**与 AaaJ 原始工具层的对比**:AaaJ 用 tree-sitter/BM25/embedding 运行时构建图谱(只支持 Python,绑 workspace,重依赖)。graphify 路线用预构建图谱(25+ 语言,不绑 workspace,零额外依赖,查询 sub-ms)。替代 AaaJ 的 DevGraph/DevLocate/DevRead/DevCodeSearch 四个模块,且更准更快。不替代 DevTextRetrieve(轨迹评估,需要 agent 执行日志,图谱不覆盖)。

`severity` 为枚举(critical > major > minor > pass,显式排序);`consensus_score` 是 reviewer 间一致度(非聚合置信度);`stability_score` 是辩论前后立场稳定性;`calibrated_confidence` 是元审查校准后的置信度(升级判定优先使用);`route` 记录流程决策路径(可审计)。

---

## 5. 功能性需求

### FR-1: 多阶段通用审查

系统必须能在 AI 介入的任意环节进行审查,通过外部配置定义各阶段的审查维度,而非硬编码特定阶段。审查范围覆盖 2.1(需求分析各子阶段)、2.2(代码生成后各子阶段)、2.3(外部代码检视产物)三组场景。

- 输入是任意文本(需求文档/规格/代码/审查报告等)
- 不依赖文件系统路径或特定数据结构(如 workspace、trajectory)
- 同一系统支持上述所有审查范围,通过切换 reviewer 配置实现
- 每个子阶段有对应的示例 reviewer 模板(见 7.3 内置模板清单)

### FR-2: 多 Agent 对抗审查策略

系统必须支持以下审查策略(前两项为核心,后两项为补充):

| 策略 | 描述 | 状态 |
|---|---|---|
| **多 agent 辩论** | N 个 reviewer 独立评审 → 1-3 轮对抗辩论(互相挑战) → 盲评终判 → 裁决合成 | 核心 |
| **交叉审查** | 一个 reviewer 审查另一个 reviewer 的判断(元审查的一种形式) | 核心 |
| **多模型配置** | 不同 reviewer 可指定不同 LLM 模型(如 Claude sonnet + Claude opus + GPT-4o),避免同模型共享盲区 | 核心 |
| **多数投票** | 同一 reviewer 配置内,同一模型调用 N 次后投票聚合,作为辩论的轻量级反幻觉手段 | 正式策略(保留自 AaaJ) |

辩论阶段须满足:
- Phase 1(独立评审)各 reviewer **并行执行**,非串行
- 当 reviewer 数 < 2 时,跳过辩论阶段(单 reviewer 自说自话无对抗价值)
- **单 reviewer 快检形态下跳过盲评终判**(复核者=初判者,自检无增量价值;抗随机用 reviewer 模板的 `majority_vote` 多次独立采样,优于自我反思);`stability_score` 标记 `degraded=true`
- 辩论轮次后计算 **stability score**(多轮辩论后观点稳定性),作为共识可信度的辅助指标

**流程决策自动化**:
- **渐进式审查(默认 auto,零 LLM 预分类)**:零参数调用时**不做先验复杂度分类**,而是**哨兵先行 + 结果驱动门控**——流程强度由 Phase 1 的实测信号决定,而非入口处的内容预测(详见 4.1 节)
- **规则自动(流程主体)**:全部流程跳过/短路由确定性代码规则决定(reviewer 计数/预算数字/置信度阈值比较/门控规则),可复现;LLM 对流程主体零决定权
- **人工覆盖(可选)**:`--profile fast/standard/thorough` 半决策,或细粒度参数全决策;显式参数跳过渐进式,直接按指定参数执行
- 成本特征:简单内容(哨兵干净通过)1 次调用;中等 ~9 次;复杂 ~15 次;相比先验 LLM 路由省去入口分类调用
- 早停判定保守设计:置信度阈值从高(0.9),错向代价不对称——不必要续跑仅浪费 ~10 次调用,错误早停会漏审关键问题
- **执行载体**:门控与 4 阶段流程在引擎的 prepare/resume 状态机中确定性推进(见 FR-11);宿主侧 judge-manager 仅机械执行任务(拉起 reviewer Agent / 落盘 / 调引擎),不参与任何流程决策

### FR-3: LLM 能力宿主化(用户零模型配置)

主流场景下,全部 reviewer 的 LLM 能力(模型、凭证、额度)来自宿主 agent 已有配置,系统不得要求用户单独配置模型串或 API key。

- **执行载体**:每次 reviewer 调用 = 宿主内拉起一个匿名 reviewer Agent(FR-10 安装产物);reviewer 的 persona + 审查框架由引擎编译进 task prompt,judge-manager 逐字传给匿名 reviewer 执行;未声明 `model` = 宿主默认模型
- **宿主命名空间**:codeagent/claude-code 系宿主仅支持 Anthropic 系模型(`opus`/`sonnet`/完整模型 ID);opencode 系宿主支持其已配置的任意 provider(`provider/model` 格式,含自定义网关)。**异构面板**(不同角色不同模型形成对抗)在 litellm 直连模式下完整保留;agent 驱动模式下 reviewer 使用宿主默认模型(匿名槽位),如需异构模型请用 `--llm litellm`
- **凭证**:完全由宿主管理(登录态/订阅额度/provider key),引擎不接触、不解析、不存储任何凭证
- **litellm 直连回退**:`--llm litellm` 强制走引擎内置 litellm 后端,服务 CI/无宿主场景;此时模型串为 litellm 命名空间,凭证经环境变量
- 主路径不引入宿主专有的 headless CLI 依赖(见 NFR-7)

### FR-4: 置信度评分与人工升级

系统必须对每条审查发现和整体裁决给出量化置信度,并基于阈值决定是否升级人工审查。

- 每条 finding 包含 `confidence: float (0.0-1.0)`
- 整体 Verdict 包含聚合后的 `confidence`
- 可配置阈值(默认 0.8):**置信度低于阈值的标记 `escalate_to_human: true`**
- 经过元审查的,使用**校准后的 confidence**(`calibrated_confidence`)作为升级判定依据
- 置信度通过结构化输出 schema 强制约束,而非依赖 LLM 自由文本解析。解析层提供多级降级(JSON 代码块 → 裸 JSON → 标签降级),确保鲁棒性
- **`severity` 字段使用枚举类型**(非裸字符串),避免字符串字典序比较导致的"最严判定"逻辑错误

### FR-5: 入口形态——judge-manager 主 Agent;CLI 为引擎与安装器

- **主流入口**:宿主内的 `judge-manager` 实体 Agent(FR-10 安装)。职责仅限:初始化运行 → 按引擎指令机械执行(拉起匿名 reviewer Agent / 落盘结果 / 调用引擎推进)→ 终态向用户汇报(findings 摘要 / escalate 标记 / route 路径审计)。**不安装宿主 skill**——意图匹配由 judge-manager 的 description 完成
- **引擎 CLI**:命令全称 **`agent-judges`**(避免短名冲突,废弃 `aj`)。子命令:`review`(审查)/ `install`(安装,FR-10)/ `list-reviewers` / `list-skills` / `inspect-reviewer` / `evaluate`
- `review` 支持三种输入:`--content` / `--file` / stdin 管道;`--file` 的 `.json` 后缀自动提取 verdict 文本(元审查场景)
- **零参数即全自动**:`agent-judges review --file x.md` 不带流程参数时走渐进式审查(FR-2),全程用户零决策;`--profile fast/standard/thorough` 显式选档;细粒度参数跳过渐进式,按指定参数执行
- **prepare/resume 接口**(agent 驱动模式):`agent-judges review --file X` 初始化并发出首批任务后退出;`agent-judges review --resume` 消费结果、确定性推进、发出下一批任务或产出终态。运行产物拆分为 logs(`.harness/logs/judges/<run_id>/`:state/tasks/results)与 evidence(`.harness/evidence/judges/<run_id>/`:verdict/report)。driver 协议见 FR-11
- **direct 模式**(`--llm litellm`):引擎进程内完成全部 LLM 调用,服务 CI/裸机;`--max-cost`/`--model`/`--override-model` 仅此模式有效
- `--interactive` 模式保留(低置信度暂停等 stdin 人工裁决;仅 direct 模式可用)
- 不作为 Python 库嵌入 agent 运行时

### FR-6: 外部定义审查 Agent

审查者(reviewer)必须可通过外部配置文件定义,无需改代码。

- **配置格式:Markdown**(`reviewers/*.md`:YAML frontmatter + persona 正文,与 skills/ 的 SKILL.md 同族);过渡期兼容读取 `*.yaml`
- frontmatter 字段:`name`、`description`、`model`(**可选,宿主命名空间**,见 FR-3/FR-10)、`weight`、`majority_vote`(同模型多次调用投票数,默认 1)、`skills`(知识包引用);checklist 写在 frontmatter,**persona 即 Markdown 正文**(原 system_prompt)
- 系统从指定目录加载所有 reviewer 配置;`agent-judges install` 据此生成宿主实体 Agent(FR-10)
- **约束模型**(匿名槽位 + 模板注入):系统提供匿名的辩论 reviewer 槽位(行为框架固定),用户模板只注入"审查视角"(persona + checklist),**不能自定义辩论行为、输出格式、流程编排**——这些由系统固定控制(见 design.md 1.6 节)
- 用户可自定义任意审查视角模板(如 `security-auditor`、`compliance-reviewer`)
- **外部审查 skill(知识注入型)**:用户可通过 SKILL.md 格式定义审查知识包,由通用匿名 agent 槽位加载。两种方式:① reviewer 模板通过 `skills: [name]` 字段引用;② CLI `-r skill:<name>` 即席加载。skill 为纯 LLM 知识包(无工具执行),与纯 LLM 审查范式一致
- reviewer 的 `model` 为可选字段(宿主命名空间),不写 = 宿主默认模型;litellm 直连模式下 `--model`/`--override-model` 语义保留
- 系统内置过程级审查模板(借鉴 CyberAgent 6 轴):过程合规(process-compliance)/欺骗检测(deception-detector)/危险操作扫描(dangerous-operation-scanner),用户传入 agent 执行日志时选择性启用

### FR-7: 提示词传递审查内容

被审查的内容通过 prompt 流入系统,而非依赖特定数据结构或文件路径解析。

- 系统接受任意文本作为被审查内容
- reviewer 的 system prompt + user prompt 组合传递被审查内容
- agent 驱动模式下:引擎生成的完整 user prompt 落盘为任务文件,driver **逐字**使用;reviewer 的 persona(system)由宿主实体 Agent 定义自带(FR-10)
- 元审查时,上一轮的 `Verdict` 序列化为文本后作为内容传入

### FR-8: 元审查(审查结果可被审查)

系统必须支持对自身输出的审查结果进行再次审查。

- `meta-reviewer` 配置定义元审查维度(漏判/过判/置信度失准/推理缺口/共识假象)
- 元审查须包含**完整性审计**(借鉴 agent-review-panel):检查原始审查是否覆盖了被审查内容的所有关键维度
- 元审查须使用**至少 2 个 meta-reviewer**(不同模型或不同 persona),形成真正对抗
- **校准必须通过显式公式实现**(非简单覆盖元审查者自身的 confidence),详见 [design.md](./design.md) 5.4 节
- CLI 支持 `--meta-review` 开关和 `--review-depth N` 参数(默认 0 = 不元审查;`--meta-review` 等价于 `--review-depth 1`)
- 元审查输出校准后的 `calibrated_confidence`
- 防止无限递归:`--review-depth` 硬上限为 2(超过报错)

### FR-9: 双格式输出

每次审查必须输出两种格式:

| 格式 | 用途 | 输出方式 |
|---|---|---|
| **Markdown 报告** | 人类阅读——含各 reviewer 发现、辩论摘要、最终裁决、置信度、升级标记 | stdout(默认)或 `--output-dir` 指定目录写文件 |
| **JSON Verdict** | 机器消费——可被下游(元审查 / CI/CD / 反馈循环)程序化处理 | stdout(当 `--output json`)或写文件(当 `--output both --output-dir`) |

> **输出语义**:`--output markdown` → Markdown 到 stdout;`--output json` → JSON 到 stdout;`--output both` → 写两个文件(`report.md` + `verdict.json`)到 `--output-dir` 指定目录。JSON **不输出到 stderr**(stderr 仅供日志/进度,避免管道冲突)。

### FR-10: 安装与平台工件(`agent-judges install`)

- 命令:`agent-judges install [--platform codeagent|claude-code|opencode|auto] [--project]`
- 默认平台 `codeagent`(claude 兼容机制,目录为 `.cac`);`--host` 为 `--platform` 的向后兼容别名
- **安装产物**(默认装平台全局目录;`--project` 装项目级),只装 2 个 Agent:
  - `judge-manager` 主 Agent(来自 `integrations/<platform>/agent/judge-manager.md` 模板)——对外可见的入口
  - `reviewer` 匿名审查槽位(来自 `integrations/<platform>/agent/reviewer.md` 模板)——无 persona 的通用槽位,不直接面向用户
- **匿名 reviewer 设计**:reviewer 的 persona + 系统固定审查框架由引擎在发出任务时编译进 task prompt(`tasks/<task_id>.md`),judge-manager 逐字传给匿名 `reviewer` Agent 执行;安装时不再从 `reviewers/*.md` 生成逐个 reviewer Agent 文件
- 安装产物是**编译产物**:`integrations/<platform>/agent/` 模板是唯一真相,修改模板后重新 install 生效
- 幂等:重复 install 覆盖并提示,输出安装清单

### FR-11: 执行模型——prepare/resume 状态机

- **编排核心纯化**:渐进式门控 / 4 阶段推进 / 合成 / 降级全部实现为纯函数;两种执行器共享同一核心——agent 驱动(任务落盘,由 judge-manager 执行)与 litellm 直连(引擎进程内执行)
- **prepare/resume 接口**:`prepare` 初始化运行并发出首批任务后退出;`resume` 消费已有结果、确定性推进、发出下一批任务或产出终态。全部流程判定记录于运行状态与 verdict 的 `route` 字段(可审计)
- **driver 协议**(judge-manager 必须遵守):循环 = 调 `--resume` → 读任务 → 逐字 prompt 原生拉起对应 Agent → 原始输出落盘 → 循环,直至终态出现;**禁止**改写 prompt / 自行增删任务 / 跳过或代答门控
- **幂等**:`--resume` 按已有结果推进,重复执行无副作用;中断后可续跑;推进前校验结果完整性,缺失任务不推进
- agent 模式下成本字段尽力而为(宿主管记账);`--max-cost` 仅 direct 模式生效

### FR-12: 主动验证（graphify 证据注入）

- 审查代码产出物时,引擎在调 reviewer 前自动尝试从本地 graphify 知识图谱收集代码结构证据,注入 reviewer prompt 的 context 部分
- **触发条件**(全部满足):① graphify CLI 在 PATH 中 ② 当前工作目录存在 `.graph/graph.json` ③ 被审查内容看起来像代码(代码文件后缀或含 def/class/function/import 等关键字)
- **不满足时静默跳过**:降级为纯 LLM 模式,用户无感知,无需配置。不影响非代码产出物(需求文档/规格/设计等)的审查
- **收集方式**:调 `graphify query`(BFS 遍历找相关节点)和 `graphify explain`(解释节点及邻居)CLI 命令,输出纯文本,拼装为 `# 代码结构证据` 注入 prompt
- **超时保护**:单次 graphify CLI 调用超时 15 秒,超时或异常静默跳过
- **reviewer 侧零改动**:证据以文本形式存在于 prompt context,reviewer 无感知证据来源,仍是纯 LLM
- **替代 AaaJ 工具层**:替代 DevGraph/DevLocate/DevRead/DevCodeSearch 四模块(代码结构证据),不替代 DevTextRetrieve(轨迹评估,需 agent 执行日志)

### FR-13: 辩论溯源标记与自动辩论强度

- **溯源标记(Phase 2 辩论)**:reviewer 在辩论中引用他人主张时,必须标注认知状态三态标记:`[✓已确认]`(在被审查内容中验证)、`[✗已反驳]`(在被审查内容中发现不成立)、`[?未验证]`(无法确认或反驳)。不带标记的引用视为无效反驳;`[?未验证]`主张不得作为调整 severity/confidence 的依据
- **自动辩论强度**:Phase 2 的质疑强度由 Phase 1 实测信号自动推断——发现 critical 或 reviewer 严重分歧(consensus < 0.5)→ 高质疑(0.9);全员一致且仅 minor/pass → 低质疑(0.4)快速收敛;其余 → 中等(0.7)。**零外部配置,用户无需调参**
- **溯源违规检测**:conformity 检测在 Phase 3 检查 reviewer 是否基于 `[?未验证]` 主张改变了立场,如发现则发出审计警告

### FR-14: 推理策略多样性

- reviewer 模板在 frontmatter 声明 `reasoning_strategy` 字段,可选值:checklist(默认,逐条核对)/ inverse(逆向验证)/ transform(变换表示)/ counterfactual(反事实推演)/ falsification(对抗性证伪)
- 系统在 system prompt 的 persona 与审查框架之间注入推理策略指引,指导 reviewer 使用不同的认知路径
- 引擎的 `deterministic_panel` 贪心选择确保面板内至少包含 2 种不同推理策略(当面板 ≥ 2 人时),打破"所有 reviewer 共享同一推理范式"的盲区
- 用户自定义模板可不声明 `reasoning_strategy`,默认为 checklist

### FR-15: 三级行动决策

- Verdict 输出 `action_level`(green/yellow/red)和 `action_reasoning`,决定审查结果如何指导行动:
  - **GREEN**(`auto_fix_eligible: true`):有效置信度 ≥ auto_fix_confidence(默认 0.9)且 severity ≤ minor 且全部 finding 有非空 suggestion → AI 可自行修复。judge-manager 向用户汇报并建议直接修复,用户确认后由原始产出 AI 按 suggestion 执行
  - **YELLOW**:有效置信度 ≥ 阈值(默认 0.8)但存在 major 问题或部分 finding 缺 suggestion → 需人工确认修复方案。judge-manager 汇报全部 findings 和修复建议
  - **RED**(`escalate_to_human: true`):有效置信度 < 阈值或 severity = critical → 必须人工介入。judge-manager 汇报完整审查报告、元审查校准结果、流程审计信息(route/consensus/stability/conformity)
- 有效置信度使用 `calibrated_confidence`(经元审查校准)优先,否则用原始 confidence
- **阈值校准**:`agent-judges evaluate --recommend-threshold` 基于历史审查数据,用 Youden's J 统计量推荐最优 escalation 阈值,替代硬编码 0.8

---

## 6. 非功能性需求

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

- Phase 1(独立评审)各 reviewer **并行执行**,而非串行
- N 个 reviewer 的独立评审耗时 ≈ max(单次延迟),而非 sum(单次延迟)

### NFR-5: 辩论稳定性度量

- 多轮辩论后计算 **stability score**(观点稳定性):若 reviewer 在多轮辩论中立场未翻转,稳定性高;若频繁翻转,共识可信度低
- stability score 作为 `consensus_score` 的辅助指标写入 JSON 输出

### NFR-6: 开源合规

基座选 MIT 许可的组件,改造后系统可自由使用和分发。

### NFR-7: 宿主可迁移性

主路径(agent 驱动模式)对宿主的依赖收敛为三项公共能力:①Agent 定义文件(Markdown + frontmatter,业界事实标准)②原生 subagent 拉起 ③shell。**不得引入宿主专有的 headless CLI 调用**(如 `claude -p` / `opencode run`——各家旗标差异是迁移阻碍);新增平台支持 = 新写一份 judge-manager + reviewer 驱动定义模板(`integrations/<platform>/agent/`),引擎与 reviewer 源零改动。

---

## 7. 外部扩展机制

### 7.1 reviewer 模板定义

reviewer 通过 Markdown 文件定义(`reviewers/*.md`):YAML frontmatter + persona 正文。

**frontmatter 字段**:

| 字段 | 说明 |
|---|---|
| `name` | 唯一标识(slug 格式) |
| `description` | 一句话描述 |
| `model` | 可选,宿主命名空间(claude 系 `opus`/`sonnet`;opencode 系 `provider/model`)。省略 = 宿主默认模型 |
| `reasoning_strategy` | 可选,推理策略(checklist/inverse/transform/counterfactual/falsification)。省略 = checklist。系统据此注入推理策略指引,引擎确保面板内推理策略多样性 |
| `weight` | 聚合权重(默认 1.0) |
| `majority_vote` | 同模型多次调用投票数(默认 1,>1 时启用多数投票) |
| `skills` | 知识包引用列表(可选) |

**persona 正文**:Markdown 正文即 reviewer 的人设与关注维度(原 system_prompt)。checklist 写在 frontmatter 中。

**约束模型(匿名槽位 + 视角注入)**:系统提供匿名的辩论 reviewer 槽位(行为框架固定),用户模板只注入"审查视角"(persona + checklist)。用户可自定义 persona / checklist / model / weight / majority_vote,**不能自定义辩论行为 / 输出格式 / 流程编排**——这些由系统固定控制,保证辩论流程兼容。

### 7.2 skill 知识包定义

skill 是用户自定义的审查知识包,采用 SKILL.md 格式(Markdown 正文 + YAML frontmatter,兼容业界 skill 约定)。纯 LLM 知识包,不含工具执行。

**两种加载方式**:

| 方式 | 用法 | 说明 |
|---|---|---|
| 模板引用 | reviewer frontmatter 中 `skills: [name]` | skill 正文注入该 reviewer 的 persona |
| 即席加载 | CLI `-r skill:<name>` | 匿名槽位直接以 skill 为完整审查视角 |

skill frontmatter 可携带 `checklist` 字段,支持即席加载时作为检查清单。两种磁盘布局:`skills/<name>/SKILL.md`(目录式)或 `skills/<name>.md`(平铺式)。

### 7.3 内置模板清单

| 模板 | scenes | 覆盖场景 |
|---|---|---|
| `spec-reviewer` | document | 规格文档（完整性、可追溯性、契约、歧义消除、MECE、验收标准可测试性） |
| `design-reviewer` | document | 设计文档（架构决策、风险消解、失败模式） |
| `test-plan-reviewer` | document | 测试计划（测试分层、回归策略、数据环境） |
| `documentation-reviewer` | document | 文档（API 文档/README，示例可运行性、参数完整性） |
| `deception-detector` | document, review-report | 欺骗检测 + 过程合规（claim vs 证据、执行痕迹） |
| `implementation-vs-requirement-reviewer` | code | 代码是否满足需求（非代码风格） |
| `unit-test-reviewer` | code | 单元测试（断言有效性、mock 合理性、测试独立性） |
| `integration-test-reviewer` | code | 集成测试（接口契约、超时/重试/幂等、环境策略） |
| `deployment-config-reviewer` | code | 部署配置（Dockerfile/IaC 安全基线、可运维性） |
| `dangerous-operation-scanner` | code | 危险操作扫描（引用 dangerous-operations skill） |
| `external-code-review-auditor` | review-report | 外部代码检视报告审查（覆盖度、误报、漏报） |
| `meta-reviewer` | —（系统内部） | 元审查 |
| `meta-reviewer-2` | —（系统内部） | 元审查（异构对抗） |

### 7.4 内置 skill 清单

| skill | 用途 |
|---|---|
| `dangerous-operations` | 危险操作正则模式清单 + 语义判定指引(被模板引用) |
| `owasp-top10` | OWASP Top 10 安全审查知识包(含 checklist,可即席加载) |
| `api-contract-review` | API 契约完整性审查(平铺式示例) |

---

## 8. 术语表

| 术语 | 含义 |
|---|---|
| **reviewer** | 审查者,由 `reviewers/*.md`(Markdown + frontmatter)定义;安装后为宿主实体 Agent |
| **Severity** | 严重程度枚举(`critical` / `major` / `minor` / `pass`),显式排序 `critical > major > minor > pass`,避免字符串字典序比较错误 |
| **Verdict** | 审查裁决,系统的核心输出数据结构 |
| **finding** | 单条审查发现(含 severity / confidence / evidence / suggestion) |
| **consensus_score** | 共识度,反映 reviewer 之间在 satisfied 判定上的一致程度(0.0 = 完全分歧,1.0 = 完全一致),非聚合置信度 |
| **stability_score** | 稳定性,多轮辩论后 reviewer 观点的稳定程度(立场未翻转 = 高稳定),作为共识可信度的辅助指标 |
| **majority_vote** | 多数投票,同一 reviewer 配置内同一模型调用 N 次后投票聚合,作为轻量级反幻觉手段 |
| **元审查 (meta-review)** | 对审查结果本身的再次审查,须使用至少 2 个 meta-reviewer 形成对抗 |
| **calibrated_confidence** | 元审查通过显式校准公式修正后的置信度,用于最终升级判定(非简单覆盖) |
| **escalate_to_human** | 置信度低于阈值时标记,表示需要人工介入 |
| **渐进式审查 (progressive review)** | 零参数 auto 模式:哨兵 reviewer 先审,两道纯规则门(早停判定/续跑强度)按 Phase 1 实测结果决定流程强度,替代先验 LLM 复杂度分类 |
| **哨兵 (sentinel)** | 渐进式审查中第一个独立评审的 reviewer(按文件名/内容提示确定性选定);其高置信干净通过是早停的必要条件 |
| **skill (审查 skill)** | 用户自定义的审查知识/指令包(SKILL.md 格式),由匿名 reviewer 槽位加载。知识注入型,不含工具执行;可被 reviewer 模板引用或 `-r skill:<name>` 即席加载 |
| **judge-manager** | 宿主内实体主 Agent(install 安装产物):机械执行驱动协议(拉起 reviewer Agent / 落盘 / 调引擎推进),终态向用户汇报;不做任何编排决策 |
| **实体 reviewer Agent** | 安装进宿主的匿名 reviewer 实例(Agent 定义文件,无 persona);由 judge-manager 按引擎任务拉起,reviewer 的 persona 由引擎编译进 task prompt 逐字传递,不直接面向用户 |
| **run-dir / prepare-resume** | 一次审查的运行目录与引擎状态机接口:prepare 发出任务后退出,resume 消费结果确定性推进(FR-11)。运行状态可审计、可断点续跑 |
| **主动验证 (active verification)** | 引擎在调 reviewer 前从 graphify 知识图谱收集代码结构证据(调用链、依赖关系),注入 reviewer prompt 的 context 部分。reviewer 仍为纯 LLM,不执行工具,但 prompt 里多了代码结构证据。graphify 不存在时静默降级为纯 LLM 模式 |
| **证据注入 (evidence injection)** | 主动验证的实现方式:证据收集发生在 reviewer 调用之前,证据以文本形式拼入 prompt,reviewer 无感知证据来源。区别于"工具执行"(reviewer 自己调工具),证据注入不改变纯 LLM 范式 |
| **graphify** | 预构建的代码知识图谱(SQLite + JSON,25+ 语言,全 AST 精确解析)。引擎通过 `graphify query` / `graphify explain` CLI 命令查询相关子图,获取调用链和依赖关系文本 |

---

## 9. 在 Claude Code / OpenCode 中使用

### 9.1 安装

```bash
# 默认 codeagent 平台(.cac 目录),装全局
agent-judges install

# 显式指定平台,装项目级
agent-judges install --platform opencode --project
```

安装产物:judge-manager Agent + 匿名 reviewer Agent(仅 2 个)。安装产物是编译产物,修改 `integrations/<platform>/agent/` 模板后重新 install 生效。reviewer 的 persona 在运行时由引擎编译进 task prompt,不需要为每个 reviewer 安装单独的 Agent 文件。之后在宿主会话里直接说"帮我对抗审查这份 spec.md",宿主委派 judge-manager 完成审查。

### 9.2 凭证继承

LLM 凭证优先从调用方会话环境继承,解析顺序:显式参数 > 环境变量 > litellm 内部回退。

**Claude Code**:`ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` / `CLAUDE_CODE_OAUTH_TOKEN`(`claude setup-token` 导出)均可自动继承;Pro/Max 订阅登录(`/login`)的 OAuth 凭证不导出到子进程环境,**不可复用**,需改用 `claude setup-token` 或设置 `ANTHROPIC_API_KEY`。注意:宿主设置 `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` 时所有凭证会从子进程环境中剥离,需在 `.env` 显式配置或经本地网关访问。

**OpenCode**:provider 凭证存储在 `~/.local/share/opencode/auth.json`,不导出为子进程环境变量。两种接法:① 安装社区插件 `opencode-llm-proxy`(本地 127.0.0.1:4010,线协议兼容),配合 `--base-url` 使用;② 在启动 opencode 的 shell 中显式 export provider key。

**解析顺序速查**:
- `anthropic/*` 模型:`--base-url`/显式参数 > `ANTHROPIC_API_KEY` > `ANTHROPIC_AUTH_TOKEN` > `CLAUDE_CODE_OAUTH_TOKEN` > `ANTHROPIC_BASE_URL`
- `openai/*` 模型:`OPENAI_API_KEY` / `OPENAI_BASE_URL`
- 无凭证时 CLI 给出可操作提示(本地模型如 `ollama/*` 不误报)

### 9.3 使用示例

```bash
# 零参数全自动(推荐):渐进式审查自动选档位与 reviewer 组合
agent-judges review --file ./spec.md

# 半决策:显式选档
agent-judges review --file ./spec.md --profile thorough

# 全决策:细粒度参数
agent-judges review --content "需求文本..." \
  -r requirement-elicitation-reviewer -r spec-reviewer \
  --debate-rounds 2 --threshold 0.8

# 管道接入(Claude Code / OpenCode / CI)
cat requirements.md | agent-judges review -r requirement-elicitation-reviewer -o json | jq '.verdict.escalate_to_human'

# 元审查:审查上一轮的审查结果
agent-judges review --file verdict.json --meta-review -o json > meta_verdict.json

# 双格式输出到目录
agent-judges review --file ./spec.md --output both --output-dir ./reports

# 即席加载 skill 为审查视角
agent-judges review --file api-spec.md -r skill:api-contract-review
```

### 9.4 输出格式

`--output markdown`(默认)→ stdout 人类可读报告;`--output json` → stdout 机器可读 verdict;`--output both --output-dir DIR` → 写 `report.md` + `verdict.json` 两个文件。JSON 不输出到 stderr(stderr 仅供日志)。

JSON verdict 核心字段:`severity`(枚举,显式排序)、`confidence`(聚合置信度)、`calibrated_confidence`(元审查校准后,升级判定优先使用)、`escalate_to_human`(是否需人工介入)、`findings`(发现列表,含 description/severity/confidence/evidence/suggestion)、`route`(流程决策路径,可审计)、`consensus_score`(reviewer 间一致度)、`stability_score`(辩论立场稳定性)、`cost`(token 与费用)。

---

## 10. 选型调研结论

### 10.1 对照结论

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

### 10.2 基座选择与定位

选择 `metauto-ai/agent-as-a-judge`(fork 改造)作为基座,非得分最高,而是改造成本最低。AaaJ 已解决三件最难的事:多轮投票聚合算法、置信度计算公式、judge prompt 工程模板。这些在 LangGraph 上都要从零写。AaaJ 的短板(无辩论、绑 benchmark、无多模型、无升级路由)可通过剥离 + 扩展解决;LangGraph 的短板(无审查语义)只能从零构建。剥离比构建快。

从其他候选借鉴(不作为基座,只偷模式):CyberAgent 的双输出与过程级评估轴;agent-review-panel 的多 reviewer 辩论 + 盲评终判 + 完整性审计;LangGraph 的结构化输出与并行设计理念。

**本方案填补的空白**:业界唯一开源的、通用的、多 agent 辩论式的、可量化置信度的、自身可递归审查的 AI 产出审计 CLI。不替代 Claude Code / Codex 的实时 review,而是在 AI 产出链路中增加一个质量关卡。

详细方案见 [design.md](./design.md)。
