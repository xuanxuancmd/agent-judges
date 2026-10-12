# 对抗审查系统白盒设计方案 (Design)

---

## 1. 方案概述

### 1.1 基座选择

基座: `metauto-ai/agent-as-a-judge` (fork 改造)

- 仓库: https://github.com/metauto-ai/agent-as-a-judge
- HEAD SHA: `43c2fa7b84ef0c1522e8250576e6798bace29dd0`
- 许可: MIT
- 学术验证: ICML 2025

### 1.2 改造策略

保留: host LLM 多模型能力, DevAsk 投票与置信度算法, judge prompt 模板。
剥离: workspace 与 benchmark 耦合, 证据收集模块(DevGraph / DevCodeSearch / DevRead / DevLocate / DevTextRetrieve / Memory / Planning)。
新增: 外部 reviewer 定义(MD frontmatter), prepare/resume 状态机引擎, 辩论编排器, 渐进式门控, 升级路由, 元审查, 通用 CLI, judge-manager 宿主集成。

### 1.3 改造后定位

一个通用的、可外部定义 reviewer 的、多 agent 辩论式的、置信度驱动人工升级的、且自身可递归审查的 AI 产出审计系统。

---

## 2. 审查范式选型

### 2.1 纯 LLM vs 工具增强

本系统采用纯 LLM 驱动的审查范式, 不包含工具执行层。

| 维度 | 原始 AaaJ(混合) | 本方案(纯 LLM) | CyberAgent(混合) |
|---|---|---|---|
| 判断层 | LLM 基于 evidence 判断 SATISFIED | LLM 基于 prompt 内容判断 + 辩论 | LLM 基于 transcript + 工具验证 |
| 证据来源 | 工具收集(DevGraph / DevRead / DevCodeSearch) | prompt 文本传入(用户提供) | judge 主动调工具验证 claim |
| 工具层 | 代码专用(tree-sitter / BM25 / embedding) | 无 | 通用(Read / Grep / Bash / gh) |
| 通用性 | 绑代码 workspace | 任意文本产出物 | 绑 Claude Code transcript |
| 幻觉防护 | 工具验证 + 同模型多次投票 | 多模型 + 多 reviewer 辩论 + 元审查 | 主动验证 + 欺骗检测 |
| 依赖 | 重(spacy / sentence-transformers / opencv / tree-sitter) | 轻(host LLM / pydantic / typer) | 中(Claude Code skill) |

### 2.2 与 agent teams 架构的区别

本系统不是传统的 agent teams 架构(如 AutoGen / CrewAI / LangGraph supervisor)。reviewer 没有自主性, 不决定流程, 不调用工具, 只做判断。更接近法庭合议庭: 法官按固定流程各自独立判断, 讨论, 投票, 裁决。

| 维度 | 传统 agent teams | 本方案(结构化辩论) |
|---|---|---|
| agent 自主性 | 高, agent 自己决定何时发言、调什么工具、何时停止 | 低, reviewer 只做判断, 不决定流程 |
| 流程控制 | agent 之间协商、路由、handoff | 固定 4 阶段串行编排, reviewer 无控制权 |
| 工具使用 | agent 可以调用工具 | reviewer 无工具, 纯 LLM |
| 角色分配 | 动态, agent 可以扮演不同角色 | 静态, MD 定义固定角色 |
| 对话模式 | 自由对话, 消息传递 | 结构化辩论(独立, 辩论, 盲评, 合成) |

### 2.3 放弃主动验证与轨迹评估的取舍

放弃工具层和轨迹评估有三个原因。

第一, AaaJ 的工具层(tree-sitter / BM25 / embedding)只对 Python 代码有效。审查需求文档、规格、设计文档时, 这些工具完全无用。本系统的审查范围横跨软件开发全管线, 不限于代码。

第二, 工具层绑 workspace 路径, 必须传入文件系统目录。这破坏了"管道纯文本输入"的设计目标, 也阻碍与 CI/CD 和宿主 agent 的集成。

第三, 轨迹评估(AaaJ 的 retrieve 模块)只适用于评估 coding agent 的执行过程, 不适用于评估产出物本身。本系统审查的是产出物, 不是执行轨迹。

代价: reviewer 的 finding 无法被工具验证。reviewer 说"需求遗漏了 X"时, 系统不会跑工具去原始文档中搜索验证 X 是否真的遗漏。这是纯 LLM 方案的固有局限。

补偿: 四层反幻觉机制。多模型配置(不同 reviewer 用不同 LLM, 避免同模型共享盲区), 多 reviewer 辩论(N 个独立评审后 1-3 轮对抗辩论), 元审查(至少 2 个 meta-reviewer 审查审查结果), 多数投票(同模型多次调用 + 投票聚合, 保留 AaaJ 原始算法)。

### 2.4 reviewer 约束模型

系统提供匿名的辩论 reviewer 槽位, 行为框架固定。用户模板只注入"审查视角"(persona + checklist), 不能自定义辩论行为、输出格式、流程编排。这些由系统固定控制, 保证辩论流程兼容。

| 维度 | 用户可自定义(MD 模板) | 系统固定控制(匿名框架) |
|---|---|---|
| 角色人设 | persona 正文(Markdown) | |
| 审查维度 | checklist(frontmatter) | |
| 模型偏好 | model(可选, 宿主命名空间) | |
| 权重 | weight | |
| 多数投票 | majority_vote | |
| 温度 | temperature(可选) | |
| 辩论行为 | | Phase 1 / 2 / 3 的提示词框架 |
| 输出格式 | | Verdict 的 JSON schema |
| 流程编排 | | 4 阶段串行 + 并行调度 |
| 知识包引用 | skills(引用 SKILL.md) | skill 加载机制 |

reviewer 在辩论中没有自己的名字身份。它是一个匿名判断单元, 加载用户模板后以模板中的 persona 视角参与固定流程的辩论。系统不暴露"agent"概念, 对外只暴露"视角模板"。

### 2.5 接入方式

| 接入方式 | 支持 | 说明 |
|---|---|---|
| CLI 管道 | 是 | `agent-judges` 独立命令行工具, 通过 stdin / stdout 文本交互。任何能调 shell 的系统都能用 |
| 宿主 Agent 集成 | 是 | `agent-judges install` 将 judge-manager + reviewer Agent 装入宿主, 会话内直接触发审查 |
| Python 库嵌入 | 否 | 不在 agent 运行时中 import, 避免耦合 |

主流场景是宿主集成: 用户在 Claude Code 或 OpenCode 会话中提出审查诉求, 宿主委派 judge-manager 实体 Agent 完成审查。LLM 能力(模型、凭证、额度)全部来自宿主已有配置, 用户零模型配置。CLI 直连模式(`host LLM`)保留为 CI 和裸机回退。

---

## 3. 候选方案对比与选型

### 3.1 四候选对照

| 需求 | agent-as-a-judge | CyberAgent skill | LangGraph oversight | agent-review-panel |
|---|---|---|---|---|
| 多阶段通用审查 | 绑 DevAI benchmark | 仅过程验证 | 通用图 | 偏代码 / 计划 |
| 多 agent 辩论 | 仅同模型多次投票 | 单 judge | 需自建 | 4-6 reviewer + 1-3 轮辩论 |
| 交叉审查 | 无 | 无 | 需自建 | 有验证轮 |
| 多模型配置 | 全模块同一 DEFAULT_LLM | 硬编码 sonnet | 原生 per-agent | 仅 Claude Code |
| 置信度 + 升级 | confidence 已算, 无升级路由 | 仅 3 级枚举 | 需自建 | 有 tier 分配 |
| 独立 CLI | benchmark 专用 | Claude Code skill | 纯库 | Claude Code plugin |
| 通用性 | 绑 workspace + trajectory | 绑 transcript JSONL | 通用 | 代码 / 计划 / 文档 |
| 元审查 | 无 | 无 | 无 | 无 |

### 3.2 选型理由

AaaJ 已解决三件最难的事: 多轮投票聚合算法(`DevAsk.check()` 的 majority_vote + satisfied_ratio), 置信度计算公式(`confidence = max(satisfied_ratio, 1 - satisfied_ratio)`), judge prompt 工程模板。这些在 LangGraph 上都要从零写。

LangGraph 的短板是审查语义全自建。`interrupt()` 绑定 Pregel + checkpointer, 对 CLI 是负担。`langgraph-supervisor` 已软弃用。审查语义(辩论拓扑、置信度 schema、评分 prompt、升级路由)全需自建, 约 500-1000 行代码。

AaaJ 的短板(无辩论、绑 benchmark、无多模型、无升级路由)可通过剥离 + 扩展解决。LangGraph 的短板(无审查语义)只能从零构建。剥离比构建快。

### 3.3 借鉴模式

| 来源 | 借鉴模式 | 融入方式 |
|---|---|---|
| CyberAgent | 双输出(Markdown + JSON), 过程级评估 6 轴 | 输出格式设计, 3 个内置过程级 reviewer |
| agent-review-panel | 多 reviewer 辩论(1-3 轮) + 盲评终判 + 完整性审计 | 辩论编排器的设计蓝图 |
| LangGraph | `with_structured_output(Pydantic)` 强制结构化置信度输出 | judge prompt 的输出 schema 设计 |

---

## 4. 目标架构

### 4.1 目录结构

src/agent_judges/ 的实际 v2 结构(37 个 Python 文件):

    src/agent_judges/
    ├── __init__.py
    ├── types.py                      Severity 枚举, Verdict / Finding Pydantic schema
    ├── reviewer.py                   MD frontmatter + persona 加载, ReviewerRegistry
    ├── skill.py                      SKILL.md 知识包加载(模板引用 / 即席加载)
    ├── debate.py                     4 阶段辩论编排(host LLM 直连路径, 技术债: agent 模式走 engine.advance)
    ├── judge.py                      verdict 解析降级链, run_majority_vote 投票算法
    ├── consensus.py                  consensus / stability 计算, synthesize_verdict 加权合成
    ├── escalation.py                 置信度阈值, escalate_to_human 路由
    ├── meta_review.py                元审查, calibrate_confidence 校准公式, serialize_verdict
    ├── evaluation.py                 AUROC 校准验证(Mann-Whitney U, 从 AaaJ 提取)
    ├── evidence.py                   graphify 证据收集(主动验证: 检测 CLI + 调 query/explain → 注入 context)
    ├── engine.py                     prepare / resume 状态机: advance(state, results) 纯函数推进
    ├── run_state.py                  RunState 模型, Stage / TaskKind 枚举, run-dir IO
    ├── progressive.py                两道纯规则门(早停 / 续跑强度), ProgressiveDecision 审计
    ├── router.py                     确定性 reviewer 选择, PROFILE_MAP 三档, RouteDecision
    ├── llm/
    │   ├── provider.py               host LLM wrapper(多模型 DI), Cost 集成, retry
    │   ├── broker.py                 LLMBroker 多模型管理(缓存 + 累计成本 + 预算)
    │   ├── cost.py                   Cost 成本追踪(原样保留自 AaaJ)
    │   ├── structured_output.py      force_structured_output 4 级降级链
    │   └── credentials.py            凭证继承(显式参数 > 环境变量 > host LLM 回退)
    ├── prompts/
    │   ├── judge_system.py           通用 judge system prompt(含匿名框架)
    │   ├── judge_user.py             通用 judge user prompt(接受任意内容)
    │   └── debate.py                 辩论轮次 prompt 构建器
    ├── cli/
    │   ├── __init__.py               typer app 注册
    │   ├── __main__.py               python -m 入口
    │   ├── review.py                 review 子命令(host LLM 直连模式)
    │   ├── review_flow.py            review 流程编排(渐进式 / fixed)
    │   ├── install.py                install 子命令(编译 reviewer + 模板 → 宿主 Agent)
    │   ├── inspect.py                inspect-reviewer 子命令
    │   ├── evaluate.py               evaluate 子命令(AUROC)
    │   └── agent_review.py           agent 驱动模式(prepare / resume + driver 协议)
    ├── output/
    │   ├── markdown_report.py        人类可读 Markdown 报告
    │   └── json_verdict.py           机器可读 JSON verdict
    ├── utils/
    │   └── truncate.py               tiktoken 截断(head / middle / tail) + count_tokens
    └── integrations/
        ├── claude-code/agent/judge-manager.md    judge-manager 驱动定义(claude-code)
        └── opencode/agent/judge-manager.md       judge-manager 驱动定义(opencode)

仓库根目录其他关键路径:

- `reviewers/`  20 个内置 reviewer 视角模板(MD frontmatter + persona 正文)
- `skills/`     3 个内置审查 skill(dangerous-operations, owasp-top10, api-contract-review)
- `tests/`      单元测试(MockLLM, 零 token) + 集成测试(真实 API)

### 4.2 组件关系

系统分三层, 各层职责清晰隔离。

入口层是 judge-manager 实体 Agent, 安装在宿主内。它只做机械执行: 调引擎的 prepare 或 resume, 读任务文件, 逐字使用引擎生成的 prompt 拉起 reviewer Agent, 把原始输出落盘, 循环直到终态。judge-manager 不做任何流程决策。

引擎层是 agent-judges CLI 的 prepare / resume 状态机。`prepare_progressive` 或 `prepare_fixed` 初始化 RunState 并发出首批任务。`advance(state, results, configs)` 是纯函数, 消费 driver 写回的结果, 推进状态机, 发出下一批任务或产出终态。渐进式门控、4 阶段辩论、裁决合成、解析降级、升级路由全部在这里确定性执行。

LLM 层有两种执行器。agent 驱动模式下, 每次 reviewer 调用就是宿主内拉起一个实体 reviewer Agent, 模型和凭证来自宿主配置。host LLM 直连模式下, 引擎进程内直接调 LLM API, 凭证经环境变量, 服务 CI 和裸机场景。

    外部(宿主会话 / CI / shell 管道)
      │
      ▼
    入口层  judge-manager Agent(宿主内, 机械执行驱动协议)
      │    agent-judges CLI(install / review / evaluate / inspect)
      │
      ▼
    引擎层  engine.py: advance(state, results) 纯函数状态机
      │    ├── progressive.py: 门1(早停) + 门2(续跑强度)
      │    ├── run_state.py: RunState / Stage / AgentTask / run-dir IO
      │    ├── router.py: 确定性面板选择 + PROFILE_MAP
      │    ├── debate.py: 4 阶段辩论(host LLM 直连路径)
      │    ├── consensus.py: 加权合成 + consensus / stability
      │    ├── judge.py: verdict 解析降级链 + majority_vote
      │    ├── meta_review.py: 元审查 + 校准公式
      │    ├── escalation.py: 置信度 < 阈值 → escalate_to_human
      │    └── reviewer.py / skill.py: 定义加载
      │
      ▼
    LLM 层  agent 模式: 宿主实体 reviewer Agent(模型 = 宿主配置)
            host LLM 模式: llm / provider.py + broker.py(进程内直连)

### 4.3 三层架构

入口层(judge-manager Agent): 宿主内的实体 Agent, 由 `integrations/<host>/agent/judge-manager.md` 模板定义。职责是机械执行驱动协议, 不参与编排。用户在宿主会话中提出审查诉求, 宿主委派 judge-manager, judge-manager 通过 shell 调用 agent-judges CLI 的 prepare / resume 接口。意图匹配靠 judge-manager 的 description, 不引入宿主 skill。

引擎层(agent-judges CLI): prepare / resume 状态机是编排核心。所有流程决策(渐进式门控、4 阶段辩论、verdict 合成、解析降级、升级路由)都在 `engine.py` 的 `advance` 纯函数中确定性推进。这是立项根基: 单 agent 不可靠, 所以编排权不能交给 LLM。两种执行器共享同一 advance 核心, agent 驱动(任务落盘, judge-manager 执行)与 host LLM 直连(引擎进程内执行)。

LLM 层(宿主实体 reviewer Agent | host LLM 直连): 主流场景下全部 LLM 能力来自宿主已配置环境。每次 reviewer 调用等于宿主内拉起一个实体 reviewer Agent, 模型由 Agent 定义文件的 `model` 字段声明(宿主命名空间), 凭证完全由宿主管理。host LLM 直连保留为 `host LLM`(CI / 裸机回退), 非主路径。主路径不引入宿主专有的 headless CLI 调用, 宿主依赖仅限三项公共能力: Agent 定义文件, 原生 subagent 拉起, shell。

---

## 5. 核心机制设计

### 5.1 渐进式门控

渐进式门控替代了先验 LLM 复杂度分类。流程强度由 Phase 1 的实测信号决定, 而非入口处的内容预测。

起跑时用 tiktoken 全文计数。token 数低于 8000 时哨兵 1 人先行, 达到 8000 时直接 3 人面板起跑(长内容跳过哨兵单审)。reviewer 人选由文件名和内容头部做确定性静态映射, 兜底通用组合。

哨兵完成独立评审后进入门 1(纯规则): 无大于等于 major 的发现且 confidence 大于等于 0.9 则早停, 直接合成输出, 流程结束。否则进入面板扩张, 补足 3 人并行评审。

面板评审完成后进入门 2(纯规则): 存在 critical 发现或加权 confidence 低于 0.8 则 thorough 续跑(2 轮辩论 + 盲评终判 + 元审查)。其余情况 standard 续跑(1 轮辩论 + 盲评终判)。

两道门都是纯函数, 读取的是 Phase 1 已产出的 verdict 字段, 零 LLM 调用。判定结果记录在 `ProgressiveDecision` 审计记录中, 完整写入 JSON verdict 的 `route` 字段。

早停判定保守设计: 置信度阈值从高(0.9), 错向代价不对称。不必要续跑仅浪费约 10 次调用, 错误早停会漏审关键问题。

### 5.2 4 阶段辩论编排

辩论编排分四个阶段串行推进, Phase 1 和 Phase 3 内部并行。

Phase 1(独立评审): N 个 reviewer 各自独立评审, 互不知晓对方存在。host LLM 直连模式用 ThreadPoolExecutor 并行执行, agent 模式并行任务发射。单个 reviewer 失败时降级为低置信度 Verdict, 不击溃整批。reviewer 模板的 `majority_vote` 大于 1 时, 同模型多次调用后投票聚合(保留 AaaJ 原始算法)。

Phase 2(对抗辩论): 仅当 reviewer 数大于等于 2 且辩论轮数大于 0 时开启。每轮各 reviewer 看到其他人的观点后反驳。每轮前检查预算, 超限则终止辩论跳到合成。单个 reviewer 辩论失败时保留原立场。

Phase 3(盲评终判): 各 reviewer 基于辩论后的立场独立给出最终裁决。并行执行。单 reviewer 快检形态(reviewer 数为 1)跳过此阶段, Phase 1 结果直接进合成, stability_score 标记 degraded。

Phase 4(裁决合成): 加权聚合各 reviewer 的终判。最严判定用 `Severity.rank` 比较(非字符串 max), 取 rank 最高的 severity。satisfied 判定要求所有人都判 pass。加权 confidence 等于各 reviewer confidence 的权重平均。

技术债: `debate.py` 目前有两套实现。host LLM 直连路径在 `DebateOrchestrator.run` 中自持 4 阶段流程。agent 模式路径走 `engine.advance` 状态机。两者行为一致, 但代码不共享。重构目标是让 `debate.py` 直连路径也复用 `engine.advance` 核心。

### 5.3 结构化输出降级链

verdict 解析有 4 级降级, 每级 try-except, 失败则降级。

第 1 级: host LLM tool-use(Anthropic 原生支持)。将 Pydantic schema 手动转为 tool definition, 设 tool_choice 强制调用。提取 tool_calls 参数构造 Verdict。兼容所有 host LLM 版本, 不依赖不确定的 host LLM 内部 API。

第 2 级: response_format(OpenAI 专用)。在 system prompt 追加 JSON schema 约束, 设 response_format 为 json_object。解析响应 content 为 JSON。

第 3 级: prompt 注入 schema + 正则解析。在 system prompt 中注入 schema 和"用 json 代码块返回"的指令。响应先用正则匹配 json 代码块, 失败则匹配裸 JSON 对象(第一个 { 到最后一个 })。严格 Pydantic 校验。

第 4 级: `<SATISFIED>` / `<UNSATISFIED>` 标签降级(AaaJ 原方案)。前 3 级全部失败时, 检查响应中是否包含标签。有则构造低置信度 Verdict(confidence 封顶 0.5, 触发人工升级)。无则抛出解析异常。

### 5.4 共识与稳定性计算

consensus_score 反映 reviewer 之间在 satisfied 判定上的一致程度, 非聚合置信度。公式: consensus = 2 * |satisfied_ratio - 0.5|, 映射到 [0, 1]。所有人判 satisfied(ratio = 1.0)或所有人判 unsatisfied(ratio = 0.0)时 consensus = 1.0。一半对一半(ratio = 0.5)时 consensus = 0.0。3 人中 2 人 satisfied(ratio = 0.75)时 consensus = 0.5。

stability_score 反映辩论前后立场稳定性。公式: stability = 辩论前后 satisfied 判定未翻转的 reviewer 比例。所有 reviewer 立场未变则 stability = 1.0, 全部翻转则 stability = 0.0。单 reviewer 快检形态跳过辩论和盲评时, stability 标记 degraded = true, 值默认 1.0 但带诚实标注。

### 5.5 元审查与校准公式

元审查不只是"再查一遍", 核心价值是校准原始审查的置信度。

流程: 将原始 Verdict 序列化为文本(含 severity、confidence、findings、reasoning), 连同原始被审查内容作为 context, 传入至少 2 个 meta-reviewer(异构模型, 通常 Claude + GPT-4o)跑辩论。meta-reviewer 的 6 个审查维度: 漏判、过判、置信度失准、推理缺口、共识假象、完整性审计。

校准通过显式公式实现, 非简单覆盖元审查者自身的 confidence:

    calibrated = original_confidence * (1 - meta_penalty)

meta_penalty 根据元审查发现的最严重 severity:

| 元审查 severity | penalty | 含义 |
|---|---|---|
| critical | 0.5 | 严重漏判 / 过判, 大幅下调 |
| major | 0.3 | 显著问题, 中度下调 |
| minor | 0.1 | 轻微问题, 小幅下调 |
| pass | 0.0 | 元审查未发现问题, 保持原始值 |

若元审查者给出显式 `confidence_adjustment` 字段(范围 -1.0 到 +1.0), 则加权融合: adjusted = clamp(original + adjustment, 0, 1), calibrated = (calibrated + adjusted) / 2。正值表示原始审查偏保守应上调, 负值表示偏自信应下调。

防止无限递归: `--review-depth` 硬上限为 2。默认 0(不元审查), `--meta-review` 等价于 1。

### 5.6 升级路由

升级路由是一句话机制: calibrated_confidence(若经过元审查)或原始 confidence 低于阈值(默认 0.8)时, 标记 `escalate_to_human = true`。阈值可配置。升级判定用校准值优先, 确保元审查发现的问题能真正触发人工介入。

### 5.7 prepare / resume 状态机

prepare / resume 状态机是 v2 的编排核心(FR-11), 实现编排纯化: 所有流程决策是纯函数, 两种执行器共享同一 advance 核心。

`advance(state, results, configs)` 是纯函数。输入: 当前 RunState 和 driver 写回的原始结果。输出: 新 RunState 和下一批 AgentTask, 或终态。幂等: 任务在结果文件存在前视为 pending, 空文件视为已收集但失败(引擎降级, 不重发不阻塞)。中断后可续跑。

状态机有 6 个阶段: AWAITING_SENTINEL(哨兵独立评审) → AWAITING_PANEL(面板扩张并行评审) → AWAITING_DEBATE(对抗辩论) → AWAITING_FINAL(盲评终判) → AWAITING_META(元审查) → DONE。门控决定是否跳过哨兵阶段(长内容直接 3 人面板)或是否早停(门 1 通过后直接 DONE)。

run-dir 布局: `state.json`(状态机状态), `input/content.md` + `context.md`(审查目标快照), `tasks/<id>.md`(逐字 prompt) + `<id>.json`(任务元数据), `results/<id>.md`(driver 写回的 Agent 原始输出), `verdict.json` + `report.md`(终态)。

driver 协议(judge-manager 必须遵守): 循环等于调 `--resume` 读 state 和 results, 推进 advance, 读新 tasks, 逐字 prompt 原生拉起对应 Agent, 原始输出落盘到 results/, 循环直至 verdict.json 出现。禁止改写 prompt, 禁止自行增删任务, 禁止跳过或代答门控。

两种 prepare 入口: `prepare_progressive`(零流程参数, 渐进式门控)和 `prepare_fixed`(显式参数, 门控禁用, 固定辩论轮数和审查深度)。

### 5.8 流程决策三层模型

| 层 | 决策者 | 机制 | 成本 |
|---|---|---|---|
| L0 规则自动(流程主体) | 确定性代码 | reviewer 计数, 预算数字, 置信度阈值比较, 门控规则 | 零 |
| L1 渐进式门控(默认 auto) | 哨兵先行 + 结果驱动门控 | 零 LLM 预分类, 读 Phase 1 实测信号决定流程强度 | 零(门控本身) |
| L2 人工覆盖(可选) | 用户 CLI 参数 | `--profile` 或细粒度参数 | 零 |

L0 是流程主体: 全部流程跳过和短路由确定性代码规则决定, 可复现。LLM 对流程主体零决定权。渐进式的两道门同样是 L0 确定性规则。

L1 在 v2 中已从"一次轻量 LLM 分类"演进为渐进式门控(哨兵先行 + 结果驱动)。原设计的 LLM 入口路由被替换, 因为哨兵评审本身就是更好的复杂度信号, 且零额外 LLM 调用。`router.py` 的 `deterministic_panel` 做文件名和内容头部的静态映射, 不调 LLM。

L2 人工覆盖: `--profile fast / standard / thorough` 半决策, 或细粒度参数全决策。显式参数跳过渐进式, 直接按指定参数执行。

### 5.9 主动验证（graphify 证据注入）

主动验证在引擎 prepare 阶段执行, 是证据注入而非工具执行。reviewer 仍为纯 LLM, 不执行工具, 但 prompt 里多了代码结构证据。

触发条件(全部满足才收集): ① graphify CLI 在 PATH 中(shutil.which 检测) ② 当前工作目录存在 .graph/graph.json ③ 被审查内容看起来像代码(文件名有代码后缀如 .py/.ts/.go, 或内容含 def/class/function/import 等关键字且密度 >= 3)。

收集流程: 引擎调 `graphify query`(BFS 遍历找相关节点, budget 1500 tokens)和 `graphify explain`(解释文件名 stem 对应节点的邻居)。输出是纯文本(调用链、依赖关系、跨文件引用), 拼装为 `# 代码结构证据` 追加到 context。超时 15 秒, 任何异常静默跳过。

注入点: engine.py 的 prepare_progressive 和 prepare_fixed 入口处调 enrich_context(content, context, filename), debate.py 的 run 和 run_progressive 入口处同调。增强后的 context 存入 RunState.context, 后续所有阶段(Phase 1/2/3/元审查)通过 build_judge_prompt 的 context 参数自动获得证据。reviewer 侧零改动。

降级行为: graphify 不在 PATH, 或图谱文件不存在, 或被审查内容是纯文档(不是代码), 或 CLI 调用超时/失败 — 任一条件满足则返回 None, context 保持原样, 系统按纯 LLM 模式运行。用户无感知, 无需配置。

与 AaaJ 原始工具层的对比: AaaJ 用 tree-sitter/BM25/embedding 运行时构建图谱(只支持 Python, 绑 workspace, 重依赖)。graphify 路线用预构建图谱(25+ 语言, 不绑 workspace, 零额外依赖, 查询 sub-ms)。替代 AaaJ 的 DevGraph/DevLocate/DevRead/DevCodeSearch 四个模块。不替代 DevTextRetrieve(轨迹评估, 需要 agent 执行日志, 图谱不覆盖)。

---

## 6. 代码清单与职责

### 核心模块

| 文件 | 职责 |
|---|---|
| `types.py` | Severity 枚举(StrEnum + rank 排序), Verdict / Finding Pydantic schema |
| `reviewer.py` | MD frontmatter + persona 正文加载, ReviewerConfig, ReviewerRegistry |
| `skill.py` | SKILL.md 知识包加载(模板引用 / skill: 即席加载), SkillRegistry |
| `engine.py` | prepare / resume 状态机: advance(state, results, configs) 纯函数, 6 阶段推进 |
| `run_state.py` | RunState 模型, Stage / TaskKind 枚举, AgentTask, run-dir IO(new / save / load / write / read) |
| `progressive.py` | start_panel_size, should_early_stop(门1), escalation_tier(门2), ProgressiveDecision |
| `router.py` | deterministic_panel(文件名 / 内容映射), PROFILE_MAP 三档, RouteDecision |
| `debate.py` | DebateOrchestrator 4 阶段(host LLM 直连路径), DebateResult |
| `judge.py` | parse_verdict 降级链, run_majority_vote(AaaJ 投票算法), _build_verdict |
| `consensus.py` | compute_consensus, compute_stability, synthesize_verdict(加权合成), aggregate_majority_votes |
| `escalation.py` | EscalationRouter: 置信度 < 阈值 → escalate_to_human |
| `meta_review.py` | MetaReviewer, calibrate_confidence(显式公式), serialize_verdict |
| `evaluation.py` | AUROC 校准验证(Mann-Whitney U, 从 AaaJ 提取) |
| `evidence.py` | graphify 证据收集: collect_graphify_evidence(检测 CLI + 图谱 + 代码内容 → 调 CLI 拼文本), enrich_context(追加到现有 context) |

### LLM 层

| 文件 | 职责 |
|---|---|
| `llm/provider.py` | LLM 类: host LLM wrapper, 多模型 DI, Cost 集成, retry(tenacity) |
| `llm/broker.py` | LLMBroker: 多模型实例缓存, 累计成本 / token, 预算控制 |
| `llm/cost.py` | Cost 成本追踪(原样保留自 AaaJ) |
| `llm/structured_output.py` | force_structured_output: 4 级降级(tool-use → response_format → prompt + 正则 → 标签) |
| `llm/credentials.py` | 凭证继承: 显式参数 > 环境变量 > host LLM 内部回退 |

### prompts

| 文件 | 职责 |
|---|---|
| `prompts/judge_system.py` | 通用 judge system prompt, build_system_prompt(persona 合并匿名框架) |
| `prompts/judge_user.py` | 通用 judge user prompt, build_judge_prompt(content, checklist, context) |
| `prompts/debate.py` | 辩论 prompt 构建器: build_debate_user_prompt, build_blind_final_user_prompt |

### cli

| 文件 | 职责 |
|---|---|
| `cli/__init__.py` | typer app 注册, 子命令挂载 |
| `cli/__main__.py` | python -m agent_judges 入口 |
| `cli/review.py` | review 子命令(host LLM 直连模式: --content / --file / stdin) |
| `cli/review_flow.py` | review 流程编排: 渐进式 vs fixed, 调 engine.prepare / advance |
| `cli/install.py` | install 子命令: 编译 reviewer 源 + judge-manager 模板 → 宿主 Agent 定义 |
| `cli/inspect.py` | inspect-reviewer 子命令: 查看 reviewer 配置详情 |
| `cli/evaluate.py` | evaluate 子命令: AUROC 校准评估 |
| `cli/agent_review.py` | agent 驱动模式: prepare / resume + driver 协议, --resume 自动查找最新 run |

### output

| 文件 | 职责 |
|---|---|
| `output/markdown_report.py` | 人类可读 Markdown 报告渲染 |
| `output/json_verdict.py` | 机器可读 JSON verdict 序列化 |

### utils

| 文件 | 职责 |
|---|---|
| `utils/truncate.py` | tiktoken 截断(head / middle / tail), count_tokens |

### integrations(随包模板)

| 文件 | 职责 |
|---|---|
| `integrations/claude-code/agent/judge-manager.md` | claude-code 宿主的 judge-manager 驱动定义 |
| `integrations/opencode/agent/judge-manager.md` | opencode 宿主的 judge-manager 驱动定义 |

---

## 7. 选型决策记录

### 7.1 风险与对策

| 风险 | 对策 | 状态 |
|---|---|---|
| host LLM 对 Claude 结构化输出支持不完整 | structured_output.py 4 级降级链 | 已对策 |
| 辩论轮次过多导致 token 成本爆炸 | debate_rounds 默认 2, --max-cost 预算控制, broker 超限终止 | 已对策 |
| 多 reviewer 共识度计算不科学 | consensus = satisfied 一致比例, stability = 立场未翻转比例 | 已对策 |
| Claude 同模型 reviewer 有共享盲区 | 鼓励混用模型, meta-reviewer-2 强制 GPT-4o 异构 | 已对策 |
| 元审查递归成本失控 | --review-depth 硬上限 2, 默认 0 | 已对策 |
| parse_verdict 在非 JSON 输出时失败 | 3 级降级: JSON 块 → 裸 JSON → SATISFIED 标签 | 已对策 |
| severity 字符串比较导致最严判定错误 | Severity(StrEnum) + .rank 显式排序 | 已对策 |
| 单 reviewer 辩论自说自话 | reviewer 数 < 2 时跳过辩论阶段 | 已对策 |
| 元审查 confidence 非校准 | 显式公式 calibrated = original * (1 - penalty) | 已对策 |
| JSON 输出到 stderr 影响管道 | JSON 到 stdout 或文件, 不到 stderr | 已对策 |
| 独立评审串行延迟高 | Phase 1 用 ThreadPoolExecutor 并行 | 已对策 |
| LLM provider 改造丢失 Cost / retry | 新 LLM 类保留 Cost 集成 + retry 机制 | 已对策 |

### 7.2 设计决策

| 编号 | 决策 | 理由 |
|---|---|---|
| B-1 | Severity 用 StrEnum + rank 排序 | 避免字符串字典序比较导致最严判定错误 |
| B-2 | review_depth 默认 0, --meta-review 等价 1 | 避免默认元审查导致成本失控 |
| B-3 | 元审查至少 2 个 meta-reviewer, 单 reviewer 跳辩论 | 单 reviewer 无法形成对抗 |
| B-4 | 校准用显式公式, 非覆盖 confidence | 保留原始置信度信息, 可审计 |
| B-5 | 结构化输出 4 级降级链 | host LLM 对各模型的结构化输出支持不一致 |
| M-1 | 包名 agent_as_a_judge → agent_judges | 与 CLI 命名一致, 去 fork 痕迹 |
| M-2 | 删除证据收集模块 + benchmark | 通用审查不需要 workspace 绑定 |
| M-3 | 新 LLM 类保留 Cost + retry | 不丢失 AaaJ 已有能力 |
| M-4 | reviewer.model 改为可选 | 宿主默认 + per-reviewer 覆盖 |
| M-5 | consensus = satisfied 一致比例 | 非聚合置信度, 反映真实分歧 |
| M-6 | Finding 不允许 pass | findings 是问题, pass 无意义 |
| M-7 | JSON 不输出到 stderr | 避免 stderr 日志干扰管道 |
| M-8 | Phase 1 并行执行 | N reviewer 耗时约 max(单次), 非 sum |

---

## 8. 调研依据与借鉴评估

### 8.1 调研来源

| 来源 | 关键发现 |
|---|---|
| metauto-ai/agent-as-a-judge (MIT, ICML 2025) | host LLM 多模型支持, DevAsk.check() 已有 majority_vote + confidence 算法, 无辩论 / 交叉 / 升级路由, 绑 DevAI benchmark |
| CyberAgent 开发者博客 (2026-06) | Claude Code skill, 主动验证, Stop-hook, 双输出, 3 级 verdict, 6 轴固定评估, 欺骗检测 |
| langchain-ai/langgraph + langgraph-supervisor-py | interrupt() 绑 Pregel, Send 原语并行, supervisor 已软弃用, 审查语义全需自建 |
| okuuva/agent-review-panel (Claude Code plugin) | 4-6 reviewer + 1-3 轮辩论 + 盲评终判 + 完整性审计, 绑 Claude Code |
| host LLM 官方文档 | model + api_key 通用参数, Claude 原生支持 |

### 8.2 借鉴评估(精选)

| 特性 | 来源 | 本方案状态 |
|---|---|---|
| 主动验证(judge 跑工具验证 claim) | CyberAgent | 未借鉴, 纯 LLM 无工具层 |
| 6 轴固定评估 | CyberAgent | 已实现, 3 个内置过程级 reviewer 覆盖 6 轴 |
| 多 agent 辩论 + 盲评终判 | agent-review-panel | 已借鉴, DebateOrchestrator 4 阶段 |
| 多模型配置 | LangGraph | 已借鉴, LLMBroker + ReviewerConfig.model |
| 置信度评分 + 校准 | 原创 | 已实现, confidence + calibrated_confidence |
| 元审查 + 完整性审计 | 原创 | 已实现, 2 个 meta-reviewer + 6 维度 |
| 多数投票 | AaaJ | 已保留, run_majority_vote |
| Stop-hook 自动触发 | CyberAgent | 明确不支持, hook 时机不正确 |

### 8.3 与业界方案定位对比

| 方案 | 多 agent | 辩论 | 置信度 | 工具验证 | 独立 CLI | 元审查 |
|---|---|---|---|---|---|---|
| 本方案 | N reviewer | 1-3 轮 | + 校准 + 升级 | 无 | 是 | 是 |
| Claude Code 内置 review | 无 | 无 | 无 | 读文件 | skill | 无 |
| Codex 内置 review | 无 | 无 | 无 | 读文件 | 无 | 无 |
| 原始 AaaJ | 同模型多次 | 无 | 有 | 代码专用 | 绑 benchmark | 无 |
| CyberAgent | 单 judge | 无 | 3 级 | 主动验证 | skill | 无 |
| agent-review-panel | 4-6 | 1-3 轮 | tier 分配 | 无 | plugin | 无 |
| LangGraph | 自定义 | 需自建 | 需自建 | 需自建 | 纯库 | 无 |

本方案填补的空白: 业界唯一开源的、通用的、多 agent 辩论式的、可量化置信度的、自身可递归审查的 AI 产出审计系统。不替代 Claude Code 或 Codex 的实时 review, 而是在 AI 产出链路中增加一个质量关卡。

---

## 9. 实施路线图

| 阶段 | 工作量 | 交付物 |
|---|---|---|
| Phase 0: 文档修正 | 0.5 天 | spec.md + design.md 修正 |
| Phase 1: Fork + 精简 | 1.5 天 | 删除证据收集模块 + benchmark, 保留 host LLM + Cost + DevAsk 算法, 包名迁移 |
| Phase 2: 多模型注入 | 1.5 天 | LLM 类改为 DI, LLMBroker, structured_output 降级 |
| Phase 3: 外部 reviewer 定义 | 2 天 | ReviewerConfig + MD 格式 + Registry + 视角模板 |
| Phase 4: 辩论编排器 + auto 路由 | 3.5 天 | DebateOrchestrator 4 阶段, Severity 排序, consensus + stability, router |
| Phase 5: 置信度 + 升级 + AUROC | 1.5 天 | EscalationRouter + run_majority_vote + evaluation.py |
| Phase 6: 元审查 | 1.5 天 | MetaReviewer + 校准公式 + 递归深度控制 |
| Phase 7: 通用 CLI | 1.5 天 | typer CLI + 3 种输入 + JSON 输出 + --interactive + output/ 模块 |
| Phase 8: 测试 + 文档 | 2 天 | MockLLM + 测试文件 + 集成测试 + README |
| 总计 | 约 17 天 | 可用的对抗审查 CLI |

v2 增补(已落地, 2026-09-11): prepare / resume 状态机(engine.py + run_state.py), 渐进式门控(progressive.py), reviewer MD 化, judge-manager 驱动定义(integrations/), install 子命令, agent 驱动模式(cli/agent_review.py)。端到端测试覆盖早停和 thorough + 元审查两场景。遗留技术债: debate.py 直连路径尚未复用 engine.advance(双实现并存, 行为一致; 重构属技术债); design.md v2 增补章节本次补写。

---

## 10. 复用资产清单

| 维度 | 行数 / 等效 | 占比 |
|---|---|---|
| 直接代码复用 | 约 570 行 | 15.1% |
| 概念 / 思路复用 | 约 419 行等效 | 11.1% |
| 综合复用率 | 约 989 行等效 | 约 26% |
| 新建 | 其余 | 约 74% |

直接复用: Cost 成本追踪, tiktoken 截断, host LLM wrapper, AUROC 算法(Mann-Whitney U), majority_vote + satisfied_ratio + confidence 公式, SATISFIED 标签解析, judge prompt 模板。

概念复用: verdict 序列化模式, 结构化输出标签, few-shot 示例, rich Markdown 渲染, 持久化字段清理, hierarchical requirements DAG 格式, 置信度评估方法论文档。

结论: 这不是传统意义的 fork 改造, 是受 AaaJ 算法启发的重写。AaaJ 贡献了三个经学术验证的核心算法(投票聚合, 置信度公式, AUROC 评估)和一批 prompt 工程模式。编排调度, 辩论, 元审查, 升级路由, 状态机全部新建。仓库保留 fork 形态便于 git 历史追溯和 MIT 许可继承。详细清单见 git history 和 src/ 源文件。
