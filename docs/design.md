# 对抗审查系统白盒设计方案 (Design)

---

## 1. 方案概述

### 1.1 基座选择

**基座**: `metauto-ai/agent-as-a-judge` (fork 改造)
- 仓库: https://github.com/metauto-ai/agent-as-a-judge
- HEAD SHA: `43c2fa7b84ef0c1522e8250576e6798bace29dd0`
- 许可: MIT
- 学术验证: ICML 2025

### 1.2 改造策略

**保留**: litellm 多模型能力 + DevAsk 投票/置信度算法 + judge prompt 模板
**剥离**: workspace/benchmark 耦合 + 证据收集模块(DevGraph/DevCodeSearch/DevRead/DevLocate/DevTextRetrieve/Memory/Planning)
**新增**: 外部 reviewer 定义(YAML)、辩论编排器、升级路由、元审查、通用 CLI

### 1.3 改造后定位

一个通用的、可外部定义 reviewer 的、多 agent 辩论式的、置信度驱动人工升级的、且自身可递归审查的 AI 产出审计系统。

### 1.4 审查范式:纯 LLM 驱动

> **核心设计决策**:本系统采用**纯 LLM 驱动**的审查范式,不包含工具执行层。

#### 1.4.1 范式选择

| 维度 | 原始 AaaJ(混合模式) | 本方案(纯 LLM) | CyberAgent(混合模式) |
|---|---|---|---|
| 判断层 | LLM 基于 evidence 判断 SATISFIED | LLM 基于 prompt 内容判断 + 辩论 | LLM 基于 transcript + 工具验证判断 |
| 证据来源 | 工具收集(DevGraph/DevRead/DevCodeSearch) | prompt 文本传入(用户提供) | judge 主动调工具验证 claim |
| 工具层 | ✅ 代码专用(tree-sitter/BM25/embedding) | ❌ 无 | ✅ 通用(Read/Grep/Bash/gh) |
| 通用性 | ❌ 绑代码 workspace | ✅ 任意文本产出物 | ❌ 绑 Claude Code transcript |
| 幻觉防护 | 工具验证 + 同模型多次投票 | 多模型 + 多 reviewer 辩论 + 元审查 | 主动验证 + 欺骗检测 |
| 依赖 | 重(spacy/sentence-transformers/opencv/tree-sitter) | 轻(litellm/pydantic/typer/yaml) | 中(Claude Code skill) |

**选择纯 LLM 的理由**:
1. 工具层(DevGraph/DevCodeSearch 等)只能处理 Python 代码——tree-sitter 解析 AST、BM25 搜索代码片段。审查需求文档/规格/设计/测试计划时这些工具完全无用
2. 工具层绑 workspace 路径——必须传入文件系统目录,无法接受管道输入的纯文本
3. 工具层引入重依赖——spacy/sentence-transformers/opencv/tree-sitter 仅用于代码证据收集,通用审查场景不需要

**代价**:reviewer 的 finding 无法被工具验证。reviewer 说"需求遗漏了 X"时,系统不会跑工具去原始需求文档中搜索验证 X 是否真的遗漏。这是纯 LLM 方案的固有局限。

**反幻觉手段**(纯 LLM 层面):

| 手段 | 机制 | 对应原始 AaaJ |
|---|---|---|
| 多模型配置 | 不同 reviewer 用不同 LLM(Claude sonnet + Claude opus + GPT-4o) | ❌ AaaJ 全模块读同一 DEFAULT_LLM |
| 多 reviewer 辩论 | N 个 reviewer 独立评审 → 1-3 轮对抗辩论 → 盲评终判 | ❌ AaaJ 无辩论 |
| 多数投票 | 同模型多次调用 + 投票聚合(保留 AaaJ 原始算法) | ✅ AaaJ 已有 |
| 元审查 | 2 个 meta-reviewer 审查审查结果(漏判/过判/置信度失准/推理缺口/共识假象/完整性审计) | ❌ AaaJ 无元审查 |
| 置信度升级 | confidence < 阈值 → escalate_to_human | ⚠️ AaaJ 有 confidence 无升级路由 |

#### 1.4.2 与 agent teams 架构的区别

本系统**不是传统的 agent teams 架构**(如 AutoGen / CrewAI / LangGraph supervisor)。

| 维度 | 传统 agent teams | 本方案(结构化辩论) |
|---|---|---|
| agent 自主性 | 高——agent 自己决定何时发言、调用什么工具、何时停止 | 低——reviewer 只做判断,不决定流程 |
| 流程控制 | agent 之间协商、路由、handoff | 固定 4 阶段串行编排,reviewer 无流程控制权 |
| 工具使用 | agent 可以调用工具 | reviewer 无工具,纯 LLM |
| 角色分配 | 动态——agent 可以扮演不同角色 | 静态——YAML 定义固定角色 |
| 对话模式 | 自由对话/消息传递 | 结构化辩论(独立→辩论→盲评→合成) |

**类比**:更接近**法庭合议庭**(法官按固定流程各自独立判断→讨论→投票→裁决),而非**自由讨论的委员会**(成员自主发言、协商决策)。

### 1.5 接入方式:仅 CLI 管道

> **设计决策**:对外只暴露 CLI 管道方式,不作为 Python 库嵌入,不作为 skill 加载。

| 接入方式 | 支持? | 说明 |
|---|---|---|
| **CLI 管道** | ✅ 支持 | `aj` 是独立命令行工具,通过 stdin/stdout 文本与外部交互。任何能调 shell 的系统(Claude Code / OpenCode / CI/CD)都能用 |
| Stop hook 自动触发 | ❌ 不支持 | hook 时机不正确且难把握(agent 完全停止后才触发,无法在产出过程中实时审查) |
| Python 库嵌入 | ❌ 不支持 | 不在 agent 运行时中 `import`,避免耦合 |

**凭证模型(宿主会话继承)**: `aj` 是被编码 agent 通过 shell 调用的质量关卡,**不要求独立申请的 API key**——LLM 凭证从调用方会话环境继承,解析顺序:显式参数 > 环境变量 > litellm 内部回退(见 `llm/credentials.py`)。按宿主区分:

| 宿主 | 可继承的凭证 | 说明 |
|---|---|---|
| Claude Code(API key 认证) | `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | 子进程继承环境变量;`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` 会剥离 |
| Claude Code(订阅登录) | ❌ 不可继承 | `/login` 凭证存于 `~/.claude/.credentials.json`,不导出;需 `claude setup-token`(`CLAUDE_CODE_OAUTH_TOKEN`,litellm 原生识别 `sk-ant-oat*` 前缀)或显式 `ANTHROPIC_API_KEY` |
| OpenCode | ❌ 不导出 | 凭证存于 `~/.local/share/opencode/auth.json`,`opencode serve` 是管理 API 非线协议代理;推荐社区插件 `opencode-llm-proxy`(127.0.0.1:4010)+ `--base-url`,或在启动 shell 中显式 export |

无凭证时 CLI 给出可操作提示而非静默失败。

**与 Claude Code / OpenCode 搭配**:
```bash
# Claude Code 产出的需求文档,管道传入审查
claude-code generate-requirements.md | aj review -r requirement-elicitation-reviewer --debate-rounds 2

# OpenCode 产出的设计文档
opencode design-output | aj review -r design-reviewer -o json > verdict.json

# 审查 Claude Code 的代码检视报告
cat pr-review.md | aj review -r external-code-review-auditor
```

### 1.6 reviewer 约束模型:匿名槽位 + 用户模板注入

> **设计决策**:系统提供**匿名的辩论 reviewer 槽位**(行为框架固定),用户模板只注入"审查视角"(persona + checklist),不提供行为定义。不提供完全自定义 agent 的能力。

#### 1.6.1 模型:reviewer = 匿名辩论框架(固定) + 用户视角模板(注入)

```
用户模板只包含(YAML):         系统匿名框架固定控制(代码):
├── persona(角色人设)          ├── Phase 1 如何读 content + 输出 Verdict JSON
├── checklist(审查维度)        ├── Phase 2 如何看对方观点 + 反驳格式
├── model(模型偏好,可选)       ├── Phase 3 如何综合信息 + 终判格式
├── weight(聚合权重)           ├── Severity/Verdict 输出 schema
├── majority_vote(投票次数)    ├── 辩论轮次/并行调度/预算控制
└── temperature(可选)          └── 异常降级策略
```

reviewer 在辩论中没有自己的名字身份——它是一个**匿名判断单元**,加载用户模板后以模板中的 persona 视角参与固定流程的辩论。系统不暴露"agent"概念,对外只暴露"视角模板"。

#### 1.6.2 用户可自定义 vs 系统控制

| 维度 | 用户可自定义(YAML 模板) | 系统固定控制(匿名框架) |
|---|---|---|
| 角色人设 | ✅ `system_prompt`(专业领域知识) | — |
| 审查维度 | ✅ `checklist`(检查清单) | — |
| 模型偏好 | ✅ `model`(可选) | — |
| 权重 | ✅ `weight` | — |
| 多数投票 | ✅ `majority_vote` | — |
| 温度 | ✅ `temperature`(可选) | — |
| **辩论行为** | ❌ 不可自定义 | ✅ Phase 1/2/3 的提示词框架 |
| **输出格式** | ❌ 不可自定义 | ✅ Verdict 的 JSON schema |
| **流程编排** | ❌ 不可自定义 | ✅ 4 阶段串行 + 并行调度 |

#### 1.6.3 为什么不允许完全自定义 agent

辩论流程有固定结构:
- Phase 1:reviewer 需接受 content + checklist 作为输入,输出 Verdict JSON
- Phase 2:reviewer 需接受"其他 reviewer 观点"作为输入,输出反驳文本
- Phase 3:reviewer 需接受"辩论后立场"作为输入,输出终判 Verdict

如果用户的自定义 agent prompt 不兼容这个流程(如不输出 JSON 格式、不接受"其他 reviewer 观点"作为输入、不产出 severity/confidence),辩论会崩溃。

**因此**:用户的模板只是**视角注入**(persona + checklist),不是完整的 agent 行为定义。辩论的"如何看对方观点""如何给出终判"由系统的匿名框架控制。

#### 1.6.4 skill 加载(已支持:知识注入型)

系统支持外部定义**审查 skill**——用户自定义的知识/指令包,由通用匿名 agent 槽位加载。skill 采用 SKILL.md 格式(Markdown 正文 + YAML frontmatter,兼容业界 skill 约定),两种磁盘布局:

```
skills/<name>/SKILL.md     # 目录式
skills/<name>.md           # 平铺式
```

**纯 LLM 范式约束**: skill 是知识注入(rubric/模式清单/领域检查表),不能定义工具、辩论行为或输出格式。两种加载方式:

| 方式 | 用法 | 说明 |
|---|---|---|
| 模板引用 | reviewer YAML 中 `skills: [name, ...]` | skill 正文注入该 reviewer 的 system prompt |
| 即席加载 | CLI `-r skill:<name>` | 匿名槽位直接以 skill 为完整审查视角 |

```yaml
# reviewer 模板引用 skill(模板只保留 persona,知识在 skill 中维护)
name: dangerous-operation-scanner
system_prompt: |
  你审查的是 AI agent 的执行日志……
skills:
  - dangerous-operations    # 模式清单 + 语义判定指引注入
checklist: [...]
```

```markdown
# skills/owasp-top10/SKILL.md —— frontmatter 可携带 checklist,支持即席加载
---
name: owasp-top10
description: OWASP Top 10 安全审查知识包
checklist:
  - criteria: "无失效的访问控制(A01)"
---
# 审查指引正文……
```

**未来扩展(工具型 skill,当前不支持)**: 若需 reviewer 带工具能力(如代码搜索验证 claim),需新增 skill 适配层执行工具——与纯 LLM 范式冲突(design 1.4),当前明确不做。

### 1.7 保留代码 vs 新建代码

> **诚实声明**:本项目实质是**受 AaaJ 启发的重写**,不是 fork 改造。AaaJ 的价值是**经过学术验证的算法思路**(ICML 2025)而非代码基座。

#### 1.7.1 AaaJ 可复用资产完整清单(经 explore agent 深挖核实)

**直接代码复用(~570 行,15.1%)**:

| # | 资产 | 来源 | 行数 | 复用方式 |
|---|---|---|---|---|
| 1 | Cost 成本追踪 | `llm/cost.py` | 39 | 原样保留 |
| 2 | tiktoken 截断(head/middle/tail) | `utils/truncate.py` | 54 | 原样保留 |
| 3 | litellm wrapper + retry + model_info 自动检测 + is_local + get_token_count + 多模态 | `llm/provider.py` | ~231 | 保留改造(去 env 硬编码) |
| 4 | `_llm_inference()` 统一返回结构(response + token + cost + time) | `llm/provider.py:L123-144` | ~22 | 提取 |
| 5 | **AUROC 算法**(Mann-Whitney U, tie-aware, 纯 Python 无 ML 库依赖) | `scripts/evaluate_confidence.py:L100-121` | ~22 | **提取 → evaluation 模块** |
| 6 | `infer_confidence()` 多级降级推导链 | `scripts/evaluate_confidence.py:L45-64` | ~20 | 提取 |
| 7 | `build_pairs` + `accuracy` + `mean_confidence` 评估管道 | `scripts/evaluate_confidence.py:L67-92` | ~26 | 提取 |
| 8 | `_collect_judgments()` 完整投票循环(prompt 组装 + N 次调用 + stats 累积) | `module/ask.py:L71-91` | ~21 | 提取 → `run_majority_vote()` |
| 9 | confidence 公式 `max(satisfied_ratio, 1-ratio)` | `module/ask.py:L57` | ~15 | 提取 |
| 10 | `_initialize/_update_llm_stats()` stats 累积模式 | `module/ask.py:L99-113` | ~15 | 提取 |
| 11 | `<SATISFIED>`/`<UNSATISFIED>` 标签解析 | `module/ask.py:L93-97` | ~4 | 提取 → parse_verdict 降级 |
| 12 | confidence/satisfied_ratio 持久化写回(支持离线评估) | `agent.py:L198-202` | ~5 | 提取 |
| 13 | judge prompt(二选一判断框架 + 证据引用要求) | `module/prompt/*judge*.py` | ~32 | 概念保留改通用 |

**概念/思路复用(等效 ~419 行,11.1%)**:

| # | 模式 | 来源 | 用途 |
|---|---|---|---|
| 14 | verdict 序列化模式 | `memory.py:_format_judgment()` | 元审查的 Verdict→text 序列化 |
| 15 | 结构化输出标签 + 聚焦/排除指令 | `system_prompt_retrieve.py` | reviewer prompt 设计 |
| 16 | demonstration + 自定义分隔符($path$) | `prompt_locate.py` | structured_output 降级方案 |
| 17 | 动作菜单选择模式 | `system_prompt_planning.py` | 元审查维度选择 |
| 18 | 多示例 few-shot | `prompt_planning.py` | 辩论 prompt 设计 |
| 19 | rich Panel + Markdown 可视化 | `agent.py:display_judgment()` | CLI Markdown 报告渲染 |
| 20 | 持久化前字段清理(删大字段保留 stats) | `agent.py:_save_judgment_data()` | Verdict JSON 输出 |
| 21 | dataclass + from_args + hasattr 降级 | `config.py` | ReviewerConfig(已升级为 Pydantic) |
| 22 | 证据分类标签([Reference] vs [Key Evidence]) | `agent.py:check_requirement()` | prompt 中区分 content/context/辩论观点 |
| 23 | 分组统计(score by category) | `generate_report.py:score()` | 报告按 severity 分组 |
| 24 | 对齐率计算(AaaJ vs Human) | `generate_report.py:alignment()` | reviewer 间一致性 |
| 25 | hierarchical requirements DAG 格式 | `benchmark/devai/instances/` | checklist 支持 prerequisites |
| 26 | requirements/preferences 二分 | `benchmark/devai/instances/` | finding 硬性问题 vs 软性建议二分 |
| 27 | 置信度评估方法论文档(AUROC 退化诊断/校准检查) | `reports/technical_guide_confidence_estimation.md` | 系统置信度自检文档 |

**不值得复用(~3300 行,明确删除)**:graph.py(1012, tree-sitter AST)、code_search.py(424, BM25+embedding)、read.py(438, 30+格式文件读取)、text_retrieve.py(315, trajectory 检索)、locate.py(117)、statistics.py(71)、run_wiki.py(~1400, OpenWiki)、memory.py 持久层(保留序列化思路,删存储)。

#### 1.7.2 新建代码清单

| 类别 | 文件 | 职责 |
|---|---|---|
| **辩论编排** | `debate.py` | 4 阶段流程、并行调度、异常降级、预算检查 |
| **数据结构** | `types.py` | Severity 枚举、Verdict/Finding Pydantic schema |
| **reviewer 管理** | `reviewer.py` | YAML 模板加载、Registry、匿名槽位管理 |
| **元审查** | `meta_review.py` | 校准公式、多 meta-reviewer |
| **升级路由** | `escalation.py` | 置信度阈值→人工升级 |
| **CLI** | `cli.py` | typer CLI、3 种输入、双格式输出 |
| **共识计算** | `consensus.py` | consensus_score + stability_score |
| **结构化输出** | `llm/structured_output.py` | tool-use 4 级降级链 |
| **输出渲染** | `output/markdown_report.py` `output/json_verdict.py` | Markdown 报告 + JSON 序列化 |
| **评估工具** | `evaluation.py` | AUROC 校准验证(从 evaluate_confidence.py 提取) |

#### 1.7.3 复用率总结

| 维度 | 行数/等效 | 占比 |
|---|---|---|
| 直接代码复用 | ~570 行 | 15.1% |
| 概念/思路复用 | ~419 行等效 | 11.1% |
| **综合复用率** | ~989 行等效 | **~26%** |
| 新建 | 其余 | ~74% |

**结论**:这不是传统意义的 fork 改造,是**受 AaaJ 算法启发的重写**。AaaJ 贡献了三个经学术验证的核心算法(投票聚合、置信度公式、AUROC 评估)和一批 prompt 工程模式;编排调度、辩论、元审查、升级路由全部新建。

**仓库形态说明**:仓库保留 fork 形态(便于 git 历史追溯 AUROC 等算法资产的来源、继承 MIT 许可),但代码实质以重写为主(直接复用 15.1% + 概念复用 11.1%)。Phase 1 的"Fork 清理"指删除不用的 ~3300 行 + 包名迁移,不代表"大部分保留"。

---

## 2. 候选方案对比

### 2.1 四候选 × 全需求对照

| 需求 | agent-as-a-judge | CyberAgent skill | LangGraph oversight | agent-review-panel |
|---|---|---|---|---|
| 多阶段通用审查 | ⚠️ 绑 DevAI benchmark | ❌ 仅过程验证 | ✅ 通用图 | ⚠️ 偏代码/计划 |
| 多agent辩论 | ❌ 仅同模型多次投票 | ❌ 单judge | ❌ 需自建 | ✅ 4-6 reviewer + 1-3轮辩论 |
| 交叉审查 | ❌ 无 | ❌ 无 | ❌ 需自建 | ✅ 有验证轮 |
| 多模型配置 | ❌ 全模块读同一 `DEFAULT_LLM` | ❌ 硬编码 sonnet-4-6 | ✅ 原生 per-agent | ❌ 仅 Claude Code |
| Claude后端 | ✅ litellm 已支持 | ✅ 原生 | ✅ ChatAnthropic | ✅ Claude Code |
| 置信度+升级 | ⚠️ confidence 已算,无升级路由 | ❌ 仅3级枚举 | ⚠️ 需自建 | ✅ 有 tier 分配 |
| 独立CLI/库 | ⚠️ benchmark专用 | ❌ Claude Code skill | ✅ 纯库 | ❌ Claude Code plugin |
| 通用性 | ❌ 绑 workspace+trajectory | ❌ 绑 transcript JSONL | ✅ | ⚠️ 代码/计划/文档 |
| 外部定义agent | ❌ 模块硬编码 | ❌ 单skill | ✅ 自定义节点 | ⚠️ 自动persona |
| 提示词传递内容 | ⚠️ DevAsk 是 prompt-based ✅ | ✅ | ✅ state传递 | ✅ |
| 元审查 | ❌ | ❌ | ❌ | ❌ |

### 2.2 选型理由:为何 AaaJ 改造成本最低

| 判断维度 | agent-as-a-judge | LangGraph |
|---|---|---|
| 已有审查专用机械 | ✅ DevAsk.check() 的投票+置信度+阈值算法、judge prompt 模板、AgentConfig | ❌ 只有图原语,审查语义全自建 |
| 需要剥离的耦合 | DevAI benchmark 格式 + 证据收集模块 | 无需剥离(通用框架),但需从头建审查逻辑 |
| 多模型改造 | 中(4处 LLM 实例化改为 DI) | 低(原生 per-agent) |
| 辩论/交叉审查 | 高(从零建) | 高(从零建) |
| 置信度升级路由 | 低(已有 confidence 字段,加~20行路由) | 中(建 schema+prompt+阈值+interrupt) |
| CLI 通用化 | 中(解耦 benchmark,加输入适配器) | 中(从零写 typer CLI) |
| **预计工期** | **1-2周原型,3-4周生产级** | 2-4周原型,4-6周生产级 |

**核心逻辑**: AaaJ 已解决三件最难的事(投票聚合、置信度计算、judge prompt 工程)。LangGraph 的短板是审查语义全自建。剥离比构建快。

### 2.3 从其他候选借鉴的模式

| 来源 | 借鉴模式 | 融入方式 |
|---|---|---|
| CyberAgent | Stop-hook 自动触发、主动验证(judge 跑工具验证 claim 非只读 log)、双输出(Markdown + JSON with suggested_action) | 作为可选 hook 层和输出格式 |
| agent-review-panel | 多 reviewer 辩论(1-3 轮)+ 盲评终判 + 完整性审计 + 多轮合并 | 辩论编排器的设计蓝图 |
| LangGraph | `with_structured_output(Pydantic)` 强制结构化置信度输出 | judge prompt 的输出 schema 设计 |

---

## 3. 目标架构

### 3.1 目录结构

> **包名统一** (M-1): 当前 fork 的 Python 包为 `agent_as_a_judge/`,改造后统一为 `adversarial_judge/`。迁移路径: `agent_as_a_judge/` → `src/adversarial_judge/`,保留 git 历史可追溯。pyproject.toml 中 `name = "adversarial-judge"`。

```
adversarial-judge/                    # fork from agent-as-a-judge, stripped + extended
├── pyproject.toml                    # 精简依赖:去掉 spacy/sentence-transformers/opencv
├── src/adversarial_judge/
│   ├── __init__.py
│   ├── cli.py                        # 新:通用 CLI 入口(typer)
│   ├── config.py                     # 改:AgentConfig + ReviewerConfig + DebateConfig
│   ├── types.py                      # 新:Severity(StrEnum) + 全局类型定义
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── provider.py               # 保留改造:litellm wrapper(多模型 DI),保留 Cost + retry
│   │   ├── broker.py                 # 新:LLMBroker 多模型管理(缓存 + 累计成本/token)
│   │   ├── structured_output.py     # 新:force_json() tool-use 优先 + 多级降级解析
│   │   └── cost.py                   # 保留:Cost 成本追踪(原样保留)
│   ├── reviewer.py                   # 新:可插拔 reviewer 定义(从 YAML 加载)
│   ├── skill.py                      # 新:外部审查 skill(SKILL.md 知识包,模板引用/即席加载)
│   ├── router.py                     # 新:auto 路由器(入口分类→档位+reviewer组合)
│   ├── judge.py                      # 改:从 DevAsk.check() 提取,加结构化输出+升级路由
│   ├── debate.py                     # 新:辩论编排器(借鉴 agent-review-panel)
│   ├── consensus.py                  # 新:consensus_score + stability_score 计算
│   ├── escalation.py                 # 新:置信度阈值→人工升级路由
│   ├── meta_review.py                # 新:元审查(审查结果可被审查)
│   ├── evaluation.py                 # 新:AUROC 校准验证(从 evaluate_confidence.py 提取)
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── judge_system.py           # 改:通用 judge system prompt
│   │   ├── judge_user.py             # 改:通用 judge user prompt(接受任意内容)
│   │   └── debate.py                 # 新:辩论轮次 prompt
│   └── output/
│       ├── __init__.py
│       ├── markdown_report.py        # 新:人类可读报告(借鉴 CyberAgent)
│       └── json_verdict.py           # 新:机器可读 JSON(借鉴 CyberAgent)
├── reviewers/                        # 新:外部视角模板目录(注入匿名 reviewer 槽位)
│   ├── requirement_elicitation_reviewer.yaml    # 需求收集阶段
│   ├── requirement_decomposition_reviewer.yaml  # 需求分解阶段
│   ├── spec_reviewer.yaml                      # 规格文档审查
│   ├── design_reviewer.yaml                    # 设计文档审查
│   ├── test_plan_reviewer.yaml                 # 测试计划审查
│   ├── implementation_vs_requirement_reviewer.yaml  # 实现是否满足需求
│   ├── external_code_review_auditor.yaml       # 外部代码检视报告审查
│   ├── process_compliance_reviewer.yaml        # 过程合规审查(上下文获取/流程实践)
│   ├── deception_detector.yaml                 # 欺骗检测(claim与证据一致性,语义级)
│   ├── dangerous_operation_scanner.yaml        # 危险操作扫描(--no-verify/force-push/rm -rf)
│   ├── meta_reviewer.yaml                     # 元审查(视角1)
│   ├── meta_reviewer_2.yaml                   # 元审查(视角2,不同模型)
│   └── custom_example.yaml                    # 用户自定义模板示例
├── skills/                            # 新:外部审查 skill 目录(SKILL.md 知识包)
│   ├── dangerous_operations/SKILL.md           # 危险操作模式清单(被模板引用)
│   ├── owasp_top10/SKILL.md                    # OWASP Top 10(含 checklist,可即席加载)
│   └── api_contract_review.md                  # API 契约审查(平铺式)
├── tests/
│   ├── fixtures/
│   │   └── mock_llm.py               # MockLLM + MockLLMBroker
│   ├── test_reviewer.py
│   ├── test_debate.py
│   ├── test_judge.py
│   ├── test_meta_review.py
│   └── test_cli.py
└── README.md
```

### 3.2 组件关系

```
   外部(Claude Code / OpenCode / CI) ──shell管道──► ┌──────────────────────────────┐
                                                    │         CLI (cli.py)          │
                                                    │ --content/--file/stdin/...    │
                                                    └───────────────┬──────────────┘
                                                                    │
                            ┌───────────────────────────────────────▼───────────────┐
                            │                DebateOrchestrator                      │
                            │   1.独立评审(并行) → 2.对抗辩论 → 3.盲评终判(并行)      │
                            │        → 4.裁决合成(Severity.rank最严+加权置信度)       │
                            │   预算检查(broker.check_budget)贯穿各阶段间             │
                            └──┬──────────────┬────────────────┬────────────────┬───┘
                               │              │                │                │
                    ┌──────────▼─────┐ ┌──────▼──────┐ ┌───────▼──────┐ ┌──────▼───────┐
                    │ReviewerRegistry│ │  LLMBroker  │ │consensus.py  │ │ MetaReviewer │
                    │(匿名槽位+YAML  │ │(多模型管理+ │ │(consensus +  │ │(可选,复用主  │
                    │ 视角模板注入)  │ │ 预算控制)   │ │ stability)   │ │ 链路+校准公式)│
                    └──────────┬─────┘ └──────┬──────┘ └──────────────┘ └──────┬───────┘
                               │              │                                  │
                    ┌──────────▼──────────────▼──────┐              ┌───────────▼───────────┐
                    │         LLM (litellm)           │              │   EscalationRouter    │
                    │ Claude/GPT/任意 (per-reviewer)  │              │ (calibrated_confidence│
                    └────────────────────────────────┘              │  < 阈值 → 人工升级)   │
                                                                    └───────────┬───────────┘
                                                                    ┌───────────▼───────────┐
                                                                    │ output/ + evaluation │
                                                                    │(Markdown+JSON报告      │
                                                                    │ +AUROC校准验证)        │
                                                                    └───────────────────────┘
```

**元审查路径**(复用主链路):
```
Verdict(_serialize_verdict 序列化为文本) ──► DebateOrchestrator.run(content=Verdict文本,
                                            reviewer_names=[meta-reviewer, meta-reviewer-2])
                      └─► calibrated_confidence = original × (1-penalty) ──► EscalationRouter(用校准值判定)
```

**离线评估路径**(evaluation.py):
```
verdict.json(含 confidence + satisfied) + 人工标注 ──► evaluation.auroc(pairs)
                                                        └─► 验证"高置信度判断是否确实更准确"
```

---

## 4. 核心改造点

### 4.1 改造1: 精简依赖,剥离证据收集模块

**删除**(绑定 workspace 的模块,不适用于通用审查):

> 完整删除清单 (M-2):以下为根目录和各子目录中所有需要删除的文件。

```
删除(根目录):
  benchmark/                          # DevAI benchmark 全量
  reports/                            # 原有报告输出目录
  scripts/run_aaaj.py                 # 绑 benchmark 入口
  scripts/run_ask.py                  # 绑 workspace 入口
  scripts/run_statistics.py           # 依赖 DevStatistics
  scripts/run_wiki.py                 # OpenWiki 独立功能
  scripts/evaluate_confidence.py      # 绑 benchmark
  scripts/generate_report.py          # 绑 benchmark
  scripts/templates/                  # benchmark 模板
  assets/                             # 原项目图片资源(可选保留 logo)

删除(agent_as_a_judge/module/):
  code_search.py                     # DevCodeSearch (BM25+embedding)
  graph.py                            # DevGraph (tree-sitter)
  read.py                             # DevRead (文件读取)
  locate.py                           # DevLocate (文件定位)
  text_retrieve.py                    # DevTextRetrieve (trajectory 检索)
  memory.py                           # Memory (历史判断)
  planning.py                         # Planning (LLM 规划)
  statistics.py                       # DevStatistics (依赖 DevGraph)
  prompt/prompt_locate.py
  prompt/prompt_planning.py
  prompt/prompt_retrieve.py
  prompt/system_prompt_locate.py
  prompt/system_prompt_planning.py
  prompt/system_prompt_retrieve.py

删除(agent_as_a_judge/):
  agent.py                            # JudgeAgent (绑 workspace)
  config.py                           # AgentConfig (绑 workspace/benchmark)
```

**保留**(迁移至 `src/adversarial_judge/`):
- `llm/provider.py` → `llm/provider.py` — litellm wrapper(Claude 支持核心,**保留 Cost 集成 + retry 机制**)
- `llm/cost.py` → `llm/cost.py` — Cost 成本追踪(**原样保留**)
- `module/ask.py` 的 `check()` 方法的**投票+置信度算法** → `judge/ask_algorithm.py`(提取为独立函数)
- `module/prompt/prompt_judge.py` 的 prompt 模板 → `prompts/judge_user.py`(改通用,去掉"code generation"硬编码)
- `module/prompt/system_prompt_judge.py` → `prompts/judge_system.py`(改通用)
- `module/prompt/prompt_ask.py` + `system_prompt_ask.py` → `prompts/`(按需保留)
- `utils/truncate.py` → `utils/truncate.py` — `truncate_string` 通用工具(保留)

**精简后 pyproject.toml**:
```toml
[tool.poetry.dependencies]
python = "^3.11"
litellm = "^1.50.0"          # LLM 统一接口(Claude/GPT/任意)
tenacity = "^9.0.0"          # 重试
pydantic = "^2.0"            # 结构化输出 schema
typer = "^0.12"              # CLI 框架
rich = "^13.0"               # 终端 UI
pyyaml = "^6.0"              # reviewer 定义文件
# 删除: spacy, sentence-transformers, opencv-python, tf-keras,
#       tree-sitter, networkx, rank-bm25, beautifulsoup4, etc.
```

### 4.2 改造2: 多模型依赖注入(解决 AaaJ 最大短板)

AaaJ 原问题:4 处独立读 `os.getenv("DEFAULT_LLM")`,无法 per-reviewer 指定模型。改造为依赖注入。

> **保留原始能力** (M-3): 新 `LLM` 类保留 `Cost` 集成、`retry` 机制(`RateLimitError`/`APIConnectionError`/`ServiceUnavailableError`)、`is_local`、`get_token_count`。多模态能力可选保留。

```python
# src/adversarial_judge/llm/provider.py (改造后)
import warnings
import time
import json
import re
from functools import partial
from typing import Type, TypeVar
from pydantic import BaseModel, ValidationError
from litellm import completion as litellm_completion
from litellm import completion_cost as litellm_completion_cost
from litellm.exceptions import (
    APIConnectionError,
    RateLimitError,
    ServiceUnavailableError,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

T = TypeVar("T", bound=BaseModel)

class LLM:
    """统一 LLM 接口,通过 litellm 支持 Claude/GPT/任意模型。
    保留原始 Cost 集成 + retry 机制。"""

    def __init__(
        self,
        model: str,                    # 必传,不再从 env 读
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        num_retries: int = 3,
        retry_min_wait: int = 1,
        retry_max_wait: int = 10,
        llm_timeout: int = 30,
        llm_temperature: float = 0.0,  # 审查场景默认 0(确定性)
        llm_top_p: float = 0.9,
        custom_llm_provider: str | None = None,
        max_input_tokens: int = 4096,
        max_output_tokens: int = 4096,
    ):
        from adversarial_judge.llm.cost import Cost

        self.cost = Cost()
        self.model_name = model
        self.api_key = api_key
        self.base_url = base_url
        self.api_version = api_version
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.llm_timeout = llm_timeout
        self.llm_temperature = llm_temperature
        self.llm_top_p = llm_top_p
        self.num_retries = num_retries
        self.retry_min_wait = retry_min_wait
        self.retry_max_wait = retry_max_wait
        self.custom_llm_provider = custom_llm_provider

        self._initialize_completion_function()

    def _initialize_completion_function(self):
        completion_func = partial(
            litellm_completion,
            model=self.model_name,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            custom_llm_provider=self.custom_llm_provider,
            max_tokens=self.max_output_tokens,
            timeout=self.llm_timeout,
            temperature=self.llm_temperature,
            top_p=self.llm_top_p,
        )

        @retry(
            reraise=True,
            stop=stop_after_attempt(self.num_retries),
            wait=wait_random_exponential(
                min=self.retry_min_wait, max=self.retry_max_wait
            ),
            retry=retry_if_exception_type(
                (RateLimitError, APIConnectionError, ServiceUnavailableError)
            ),
        )
        def wrapper(*args, **kwargs):
            resp = completion_func(*args, **kwargs)
            return resp

        self._completion = wrapper

    def complete(self, system_prompt: str, user_prompt: str, temperature: float | None = None) -> str:
        """同步文本补全。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs = {"messages": messages}
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = self._completion(**kwargs)
        self._post_completion(resp)
        return resp["choices"][0]["message"]["content"]

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[T],
    ) -> T:
        """强制结构化输出。
        优先策略 (B-5): litellm tool-use (Anthropic 原生支持)
        降级策略: response_format (OpenAI 专用) + 正则解析
        最终降级: 标签解析
        """
        from adversarial_judge.llm.structured_output import force_structured_output
        return force_structured_output(self, system_prompt, user_prompt, schema)

    def _post_completion(self, response) -> None:
        try:
            cost = litellm_completion_cost(completion_response=response)
            if self.cost:
                self.cost.add_cost(cost)
        except Exception:
            pass

    def get_token_count(self, messages: list) -> int:
        import litellm
        return litellm.token_counter(model=self.model_name, messages=messages)

    def is_local(self) -> bool:
        if self.base_url:
            return any(
                s in self.base_url
                for s in ["localhost", "127.0.0.1", "0.0.0.0"]
            )
        if self.model_name and self.model_name.startswith("ollama"):
            return True
        return False
```

```python
# src/adversarial_judge/llm/structured_output.py (新建, B-5 修正)
"""强制结构化输出: tool-use 优先 + 多级降级解析。"""
import json
import re
from typing import Type, TypeVar
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

def force_structured_output(
    llm,
    system_prompt: str,
    user_prompt: str,
    schema: Type[T],
) -> T:
    """尝试获取符合 schema 的结构化输出,多级降级:
    1. litellm tool-use (Anthropic 原生支持 tool_use)
    2. response_format={"type": "json_object"} (OpenAI 专用)
    3. prompt 中注入 JSON schema + 正则解析
    4. <SATISFIED>/<UNSATISFIED> 标签降级 (AaaJ 原方案)
    """
    # Level 1: tool-use
    try:
        return _try_tool_use(llm, system_prompt, user_prompt, schema)
    except Exception:
        pass

    # Level 2: response_format (OpenAI)
    try:
        return _try_response_format(llm, system_prompt, user_prompt, schema)
    except Exception:
        pass

    # Level 3: prompt 注入 schema + 正则解析
    response = _prompt_based_json(llm, system_prompt, user_prompt, schema)
    return _parse_json_response(response, schema)

def _try_tool_use(llm, system_prompt, user_prompt, schema):
    """litellm tool-use: 将 Pydantic schema 转为 tool definition。
    手动构建 tool definition,不依赖不确定的 litellm 内部 API。"""
    import litellm

    # 手动构建 tool definition(兼容所有 litellm 版本)
    tool_schema = schema.model_json_schema()
    tool = {
        "type": "function",
        "function": {
            "name": "submit_verdict",
            "description": "Submit the review verdict as structured data",
            "parameters": tool_schema,
        },
    }
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    resp = llm._completion(
        messages=messages,
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "submit_verdict"}},
        temperature=0.0,
    )
    llm._post_completion(resp)  # 记录成本(与 _try_response_format 一致)
    # 提取 tool call 参数
    tool_calls = resp["choices"][0]["message"].get("tool_calls", [])
    if not tool_calls:
        raise ValueError("No tool call in response")
    args = json.loads(tool_calls[0]["function"]["arguments"])
    return schema(**args)

def _try_response_format(llm, system_prompt, user_prompt, schema):
    """OpenAI response_format (仅 OpenAI 兼容模型)。"""
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    enhanced_system = (
        system_prompt
        + f"\n\n你必须返回符合以下 JSON schema 的 JSON 对象:\n{schema_json}\n"
        f"只返回 JSON,不要其他内容。"
    )
    messages = [
        {"role": "system", "content": enhanced_system},
        {"role": "user", "content": user_prompt},
    ]
    resp = llm._completion(
        messages=messages,
        response_format={"type": "json_object"},
    )
    content = resp["choices"][0]["message"]["content"]
    llm._post_completion(resp)
    data = json.loads(content)
    return schema(**data)

def _prompt_based_json(llm, system_prompt, user_prompt, schema):
    """prompt 注入 schema 约束,获取自由文本响应。"""
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
    enhanced_system = (
        system_prompt
        + f"\n\n你必须返回符合以下 JSON schema 的 JSON 对象(用 ```json 代码块包裹):\n{schema_json}\n"
    )
    return llm.complete(enhanced_system, user_prompt)

def _parse_json_response(response: str, schema: Type[T]) -> T:
    """多级 JSON 解析降级:
    1. ```json ... ``` 代码块
    2. 裸 JSON 对象(第一个 {...})
    3. <SATISFIED>/<UNSATISFIED> 标签降级(AaaJ 原方案, capped confidence 0.5)
    """
    # Level 1: JSON 代码块
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return schema(**data)
        except (json.JSONDecodeError, ValidationError):
            pass

    # Level 2: 裸 JSON
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return schema(**data)
        except (json.JSONDecodeError, ValidationError):
            pass

    raise ValueError(f"Could not parse structured output from response: {response[:200]}...")
```

```python
# src/adversarial_judge/llm/broker.py (新建)
from adversarial_judge.llm.provider import LLM

class LLMBroker:
    """多模型管理:per-reviewer 可以指定不同模型。
    支持实例缓存 + 累计成本追踪 + 预算控制。
    成本通过 LLM._post_completion → Cost.add_cost 自动记录到各实例,
    broker 汇总缓存实例的 Cost.accumulated_cost 即得总成本。"""

    def __init__(
        self,
        default_model: str,
        default_api_key: str | None = None,
        default_base_url: str | None = None,
        max_budget_usd: float | None = None,
    ):
        self.default_model = default_model
        self.default_api_key = default_api_key
        self.default_base_url = default_base_url
        self.max_budget_usd = max_budget_usd
        self._cache: dict[str, LLM] = {}

    def get_llm(self, model: str | None = None) -> LLM:
        """获取指定模型的 LLM 实例(带缓存)。
        model 为 None 时用 default_model (M-4: reviewer.model 可选)。"""
        resolved = model or self.default_model
        if resolved not in self._cache:
            self._cache[resolved] = LLM(
                model=resolved,
                api_key=self.default_api_key,
                base_url=self.default_base_url,
            )
        return self._cache[resolved]

    def get_total_cost(self) -> float:
        """汇总所有缓存实例的累计成本。
        LLM._post_completion → Cost.add_cost 自动记录,无需手动调 record_usage。"""
        return sum(llm.cost.accumulated_cost for llm in self._cache.values())

    def get_total_tokens(self) -> int:
        """汇总所有缓存实例的累计 token 数。"""
        return sum(len(llm.cost.costs) for llm in self._cache.values())

    def check_budget(self) -> bool:
        """返回 True = 预算未超限, False = 超限应终止。"""
        if self.max_budget_usd is None:
            return True
        return self.get_total_cost() < self.max_budget_usd
```

### 4.3 改造3: 外部定义审查 Agent(YAML 配置)

新建 `reviewer.py` + `reviewers/*.yaml`。

> **字段变更** (M-4, G-5):
> - `model` 改为**可选**(`str | None = None`),不指定时用 CLI `--model` 默认值
> - 新增 `majority_vote: int = 1` 字段,保留 AaaJ 原始同模型多次投票算法作为轻量级反幻觉手段
> - `ReviewerRegistry` 加载 `*.y*ml`(同时支持 `.yaml` 和 `.yml`)

```yaml
# reviewers/requirement_elicitation_reviewer.yaml
# 需求收集阶段审查者
name: requirement-elicitation-reviewer
description: 审查需求收集阶段的AI产出,检查完整性、来源可追溯、干系人覆盖
model: anthropic/claude-sonnet-4-20250514    # 可选,不指定时用 CLI --model 默认值
system_prompt: |
  你是一位资深需求分析师,专长于发现需求文档中的:
  - 遗漏的需求(功能边界不清晰)
  - 矛盾的需求(相互冲突的约束)
  - 不可验证的需求(无明确验收标准)
  - 过度设计(超出业务目标的复杂度)

  审查时,对每条发现给出:
  1. 严重程度: critical / major / minor
  2. 置信度: 0.0-1.0
  3. 具体依据(引用被审查内容)
  4. 改进建议
checklist:
  - criteria: 所有功能需求都有明确的输入/输出/异常处理描述
  - criteria: 非功能需求(性能/安全/可用性)有可量化的指标
  - criteria: 需求之间无逻辑矛盾
  - criteria: 业务边界与系统边界一致
  - criteria: 验收标准可测试
  - criteria: 干系人需求来源已记录
weight: 1.0
majority_vote: 1    # 同模型调用次数,>1 时启用多数投票(轻量级反幻觉)
```

```yaml
# reviewers/spec_reviewer.yaml
name: spec-reviewer
description: 审查规格文档,检查需求到规格的可追溯性和契约完整性
model: anthropic/claude-sonnet-4-20250514
system_prompt: |
  你审查的是规格文档(spec)。关注:
  - 每条需求是否都有对应的规格定义(可追溯性)
  - 接口契约的完整性(输入/输出/错误码/边界)
  - 边界条件的显式覆盖
  - 验收标准的可测试性
  - 规格内部的一致性(无自相矛盾)
checklist:
  - criteria: 每条需求可追溯到具体规格条目
  - criteria: 接口契约定义完整(含异常路径)
  - criteria: 边界条件显式列出
  - criteria: 验收标准可执行
  - criteria: 规格内部无矛盾
weight: 1.0
majority_vote: 1
```

```yaml
# reviewers/external_code_review_auditor.yaml (G-1: 审查外部代码检视报告)
name: external-code-review-auditor
description: 审查外部代码检视报告的覆盖度、误报率、severity 合理性
# model 不指定,用 CLI --model 默认值
system_prompt: |
  你审查的是一份外部代码检视报告(可能来自 SonarQube / ESLint / 人工 review)。
  你的任务不是审查代码,而是审查"检视报告本身"是否可靠:

  1. 覆盖度: 检视是否覆盖了需求中的所有关键模块
  2. 误报: 报告中的问题是否真实存在(基于提供的代码上下文判断)
  3. 漏报: 需求关键路径上是否有明显问题未被检视发现
  4. Severity 合理性: 报告标注的严重级别是否与实际影响匹配
  5. 建议可执行性: 报告中的修复建议是否具体可操作

  对每个发现给出 severity / confidence / evidence / suggestion。
checklist:
  - criteria: 检视报告覆盖了需求中所有关键模块
  - criteria: 报告中标注的问题均有代码依据(非误报)
  - criteria: 需求关键路径上无明显漏报
  - criteria: severity 标注与实际影响匹配
  - criteria: 修复建议具体且可执行
weight: 1.2
majority_vote: 1
```

```yaml
# reviewers/implementation_vs_requirement_reviewer.yaml
name: implementation-vs-requirement-reviewer
description: 审查AI生成代码是否满足需求规格(非代码质量review)
model: anthropic/claude-sonnet-4-20250514
system_prompt: |
  你审查的是AI生成的代码是否满足既定需求(不是代码风格review)。
  关注:
  - 需求覆盖度: 每个需求点是否都有对应实现
  - 实现正确性: 逻辑是否与需求描述一致
  - 边界处理: 需求中的异常场景是否覆盖
  - 验收可达成性: 是否能通过需求中的验收标准

  不审查: 代码风格、命名、设计模式、性能微优化。
checklist:
  - criteria: 每条需求都有对应的代码实现
  - criteria: 实现逻辑与需求描述无偏差
  - criteria: 异常场景有处理
  - criteria: 可通过验收标准验证
weight: 1.0
majority_vote: 1
```

```yaml
# reviewers/meta_reviewer.yaml (元审查者视角1)
name: meta-reviewer
description: 审查另一个(组)AI审查者给出的审查报告,检查审查本身是否可靠
model: anthropic/claude-sonnet-4-20250514
system_prompt: |
  你审查的是另一个(组)AI审查者给出的审查报告(Verdict)。
  原始被审查内容会一并给你。你的任务是判断审查报告本身是否可信:

  1. 漏判: 原始内容中有明显问题,但审查报告未发现
  2. 过判: 审查报告标记的问题其实不成立或被夸大
  3. 置信度失准: 审查报告的 confidence 与实际证据强度不匹配
  4. 推理缺口: findings 的 evidence 不能支撑其 severity
  5. 共识假象: 多reviewer"共识"实为互相附和,非独立验证
  6. 完整性审计: 审查报告是否覆盖了原始内容的所有关键维度

  对每个元发现给出严重程度、置信度、依据、修正建议。
  同时给出置信度校准建议:
  - confidence_adjustment: float (-1.0 ~ +1.0)
    正值表示原始置信度应上调(原始审查偏保守)
    负值表示原始置信度应下调(原始审查偏自信)
  - 校准依据: 说明调整理由
checklist:
  - criteria: 审查报告覆盖了原始内容的所有关键维度
  - criteria: 每条 finding 的 evidence 确实存在于原始内容中
  - criteria: severity 与 evidence 强度匹配
  - criteria: confidence 反映了真实的不确定性
  - criteria: 无明显的漏判或过判
  - criteria: 完整性审计通过(所有关键维度已覆盖)
weight: 1.5    # 元审查权重略高,因为它修正原始审查
majority_vote: 1
```

```yaml
# reviewers/meta_reviewer_2.yaml (元审查者视角2, B-3: 使用不同模型形成对抗)
name: meta-reviewer-2
description: 元审查者第二视角,使用不同模型避免同模型盲区
model: openai/gpt-4o    # 异构模型,与 meta-reviewer 的 Claude 形成交叉验证
system_prompt: |
  你是第二元审查者,任务与 meta-reviewer 相同但使用不同视角:
  重点关注"推理链断裂"和"隐含假设未验证"两类问题。

  你的输出须包含:
  1. 元发现列表(同 meta-reviewer)
  2. confidence_adjustment: float (-1.0 ~ +1.0)
  3. 与第一元审查者的一致性评估(若提供)
checklist:
  - criteria: 推理链条无断裂(finding 的 evidence → severity 推理完整)
  - criteria: 隐含假设已显式验证
  - criteria: 完整性审计通过
weight: 1.5
majority_vote: 1
```

```python
# src/adversarial_judge/types.py (新建, D-7/D-11: Severity 枚举)
from enum import StrEnum
from pydantic import BaseModel, field_validator

class Severity(StrEnum):
    """严重程度枚举。
    使用 StrEnum 确保可序列化为字符串;
    通过 .rank 属性定义显式排序,避免字符串字典序比较错误 (B-1)。"""
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    PASS = "pass"

    @property
    def rank(self) -> int:
        """严重程度排序: critical(3) > major(2) > minor(1) > pass(0)。
        用于 _synthesize 中的 max_severity 判定。"""
        return {self.CRITICAL: 3, self.MAJOR: 2, self.MINOR: 1, self.PASS: 0}[self]


class Finding(BaseModel):
    """单条审查发现。Finding 级别不允许 pass (M-6)。"""
    description: str
    severity: Severity
    confidence: float  # 0.0-1.0
    evidence: str
    suggestion: str

    @field_validator("severity")
    @classmethod
    def severity_not_pass(cls, v: Severity) -> Severity:
        if v == Severity.PASS:
            raise ValueError("Finding.severity cannot be 'pass' — findings are issues by definition")
        return v


class Verdict(BaseModel):
    """审查裁决。整体 Verdict 允许 pass(整体通过)。"""
    severity: Severity              # overall: critical / major / minor / pass
    confidence: float              # 0.0-1.0
    reasoning: str
    findings: list[Finding]
    satisfied: bool                # 是否通过审查
    escalate_to_human: bool = False
    calibrated_confidence: float | None = None    # 元审查校准后
    original_content: str | None = None            # 元审查回溯用
    confidence_adjustment: float | None = None     # 元审查者建议的调整量
```

```python
# src/adversarial_judge/reviewer.py
from pydantic import BaseModel, field_validator
import yaml
from pathlib import Path

class ChecklistItem(BaseModel):
    criteria: str
    weight: float = 1.0    # checklist 项权重

class ReviewerConfig(BaseModel):
    name: str                              # 唯一标识(slug)
    description: str
    model: str | None = None               # 可选 (M-4),不指定时用 broker 默认
    system_prompt: str
    checklist: list[ChecklistItem]
    weight: float = 1.0                    # reviewer 在聚合中的权重
    majority_vote: int = 1                 # (G-5) 同模型多次调用投票,默认 1
    temperature: float | None = None       # 可选,覆盖默认温度
    max_output_tokens: int | None = None   # 可选,覆盖默认 token 上限

    @field_validator("name")
    @classmethod
    def name_must_be_slug(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("name must be a slug (alphanumeric + -/_)")
        return v

class ReviewerRegistry:
    """从 reviewers/ 目录加载所有外部定义的审查 agent。"""
    def __init__(self, reviewers_dir: Path):
        self.reviewers: dict[str, ReviewerConfig] = {}
        # (L-6) 同时支持 .yaml 和 .yml
        for yml_file in reviewers_dir.glob("*.y*ml"):
            data = yaml.safe_load(yml_file.read_text(encoding="utf-8"))
            config = ReviewerConfig(**data)
            self.reviewers[config.name] = config

    def get(self, name: str) -> ReviewerConfig:
        if name not in self.reviewers:
            raise KeyError(f"Reviewer '{name}' not found. Available: {list(self.reviewers)}")
        return self.reviewers[name]

    def list_all(self) -> list[ReviewerConfig]:
        return list(self.reviewers.values())
```

#### 4.3.1 过程级评估:借鉴 CyberAgent 6 轴(纯 LLM 语义级实现)

CyberAgent 的 6 轴固定评估(上下文获取/操作验证证据/危险操作/欺骗迹象/流程合规/安全检查)中,4 轴可纯 LLM 实现,2 轴可做语义级版本。本系统通过 3 个内置过程级 reviewer 模板实现(用户传入 agent 执行日志时选择性启用):

| 内置模板 | 覆盖的 CyberAgent 轴 | 实现方式 |
|---|---|---|
| `process_compliance_reviewer.yaml` | 上下文获取、流程合规、安全检查(语义级) | 审查执行日志:是否读了 spec/Issue/相关代码、是否遵循 TDD 等实践、是否有安全扫描痕迹 |
| `deception_detector.yaml` | 欺骗迹象、操作验证证据(语义级) | 提取 agent 的 claim 列表,与日志证据逐条语义比对("说做了X"vs"日志里有X的痕迹") |
| `dangerous_operation_scanner.yaml` | 危险操作 | 正则扫描(`--no-verify`/`git push --force`/`rm -rf`/`chmod 777`等) + 语义分析上下文 |

```yaml
# reviewers/deception_detector.yaml (示例)
name: deception-detector
description: 审查 agent 执行日志中 claim 与证据的语义一致性(欺骗检测,纯 LLM 语义级)
model: anthropic/claude-sonnet-4-20250514
system_prompt: |
  你审查的是 AI agent 的执行日志。你的任务是检测"欺骗迹象"——
  agent 声称做了某事但日志中缺乏证据支持:

  1. 提取 claim 列表: 扫描日志中 agent 的所有声明(如"测试已通过"、"已验证功能"、"已处理边界情况")
  2. 逐条比对证据: 每个 claim 在日志中是否有对应的执行痕迹(命令输出/文件修改/测试结果)
  3. 标记不一致: claim 无证据支持 / claim 与证据矛盾 / claim 夸大(说"全部通过"实际部分通过)

  对每个不一致给出 severity / confidence / evidence(引用日志原文) / suggestion。
  注意: 你只能做语义级比对,无法运行工具强验证——置信度应保守。
checklist:
  - criteria: 每个关键 claim 都有日志证据支持
  - criteria: claim 与证据无矛盾
  - criteria: claim 无夸大(部分成功不表述为全部成功)
  - criteria: 失败/跳过的步骤被如实声明
weight: 1.3
majority_vote: 1
```

> **与 CyberAgent 的差异声明**: CyberAgent 的 judge 可跑工具强验证(如 `gh pr checks` 验证 CI 状态);本系统纯 LLM 只能做语义级比对,置信度标注应保守。未来若引入工具层(1.6.4 skill 扩展),可升级为强验证。

### 4.4 改造4: 辩论编排器(借鉴 agent-review-panel 的辩论+盲评终判)

> **关键修正**:
> - (B-1) `_synthesize` 使用 `Severity.rank` 排序,而非字符串 `max()`
> - (M-8) Phase 1 独立评审并行执行(`ThreadPoolExecutor`)
> - (M-5) `consensus_score` = reviewer 在 satisfied 判定上的一致比例,非 final_verdict.confidence
> - (G-5) `_independent_review` 内部支持 `majority_vote` 多次调用投票
> - (B-3) 当 reviewer 数 < 2 时跳过辩论阶段

```python
# src/adversarial_judge/debate.py
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from .reviewer import ReviewerConfig, ReviewerRegistry
from .llm.broker import LLMBroker
from .types import Verdict, Finding, Severity
from .judge import parse_verdict, run_majority_vote
from .consensus import compute_consensus, compute_stability

@dataclass
class DebateResult:
    individual_verdicts: list[Verdict]          # 各 reviewer 的独立判断
    debate_rounds: list[list[str]]              # 各轮辩论的论点
    final_verdicts: list[Verdict]               # 各 reviewer 的盲评终判
    final_verdict: Verdict                       # 终审裁决(加权聚合)
    consensus_score: float                       # 共识度(0-1): reviewer 一致性
    stability_score: float                       # 稳定性: 辩论后观点稳定程度

class DebateOrchestrator:
    """
    辩论流程(借鉴 agent-review-panel 的 16 阶段流程,精简为 4 阶段):
    1. 独立评审: N 个 reviewer **并行**独立评估(无交叉)
    2. 对抗辩论: 1-3 轮,reviewer 互相挑战对方发现(**仅当 ≥2 reviewer**)
    3. 盲评终判: 每个 reviewer 独立给出最终评分(**并行**)
    4. 裁决合成: 加权聚合 → 共识度 → 最终裁决
    """
    def __init__(
        self,
        registry: ReviewerRegistry,
        broker: LLMBroker,
        debate_rounds: int = 2,
        max_workers: int | None = None,
    ):
        self.registry = registry
        self.broker = broker
        self.debate_rounds = debate_rounds
        self.max_workers = max_workers or 4

    def run(
        self,
        content: str,                           # 被审查内容(通过 prompt 传入)
        reviewer_names: list[str],              # 使用哪些 reviewer
        context: str | None = None,             # 可选背景上下文
    ) -> DebateResult:
        reviewers = [self.registry.get(name) for name in reviewer_names]
        if len(reviewers) < 1:
            raise ValueError("At least 1 reviewer required")

        # Phase 1: 独立评审(并行, M-8)
        individual_verdicts = self._parallel_independent_review(
            reviewers, content, context
        )

        # 预算检查: Phase 1 后
        if not self.broker.check_budget():
            import logging
            logging.getLogger(__name__).warning(
                f"预算超限 (${self.broker.get_total_cost():.4f}),跳过辩论阶段"
            )
            # 跳过辩论和盲评,直接用独立评审结果合成
            final_verdict = self._synthesize(individual_verdicts, reviewers, content)
            consensus = compute_consensus(individual_verdicts)
            return DebateResult(
                individual_verdicts=individual_verdicts,
                debate_rounds=[],
                final_verdicts=individual_verdicts,
                final_verdict=final_verdict,
                consensus_score=consensus,
                stability_score=1.0,
            )

        # Phase 2: 对抗辩论(仅当 ≥2 reviewer 且 debate_rounds > 0, B-3)
        debate_log: list[list[str]] = []
        if len(reviewers) >= 2 and self.debate_rounds > 0:
            current_positions = [v.reasoning for v in individual_verdicts]
            for round_idx in range(self.debate_rounds):
                # 预算检查: 每轮辩论前
                if not self.broker.check_budget():
                    import logging
                    logging.getLogger(__name__).warning(
                        f"预算超限 (${self.broker.get_total_cost():.4f}),终止辩论"
                    )
                    break
                round_arguments = self._debate_round(
                    reviewers, content, current_positions, context
                )
                debate_log.append(round_arguments)
                current_positions = round_arguments
        else:
            # 单 reviewer 或 debate_rounds=0:跳过辩论
            current_positions = [v.reasoning for v in individual_verdicts]

        # Phase 3: 盲评终判(并行)
        final_verdicts = self._parallel_blind_final(
            reviewers, content, current_positions, context
        )

        # Phase 4: 裁决合成
        final_verdict = self._synthesize(final_verdicts, reviewers, content)
        consensus = compute_consensus(final_verdicts)
        stability = compute_stability(individual_verdicts, final_verdicts)

        return DebateResult(
            individual_verdicts=individual_verdicts,
            debate_rounds=debate_log,
            final_verdicts=final_verdicts,
            final_verdict=final_verdict,
            consensus_score=consensus,
            stability_score=stability,
        )

    def _parallel_independent_review(
        self, reviewers: list[ReviewerConfig], content: str, context: str | None
    ) -> list[Verdict]:
        """Phase 1: 并行独立评审 (M-8)。
        单个 reviewer 失败时降级为低置信度 Verdict,不击溃整批。"""
        def work(reviewer: ReviewerConfig) -> Verdict:
            try:
                return self._independent_review(reviewer, content, context)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"Reviewer '{reviewer.name}' failed in independent review: {e}"
                )
                return Verdict(
                    severity=Severity.MAJOR,
                    confidence=0.0,
                    reasoning=f"[REVIEWER FAILED: {e}]",
                    findings=[],
                    satisfied=False,
                )

        results: list[Verdict | None] = [None] * len(reviewers)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_idx = {
                pool.submit(work, r): i for i, r in enumerate(reviewers)
            }
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                results[idx] = fut.result()
        return [r for r in results if r is not None]

    def _parallel_blind_final(
        self, reviewers, content, current_positions, context
    ) -> list[Verdict]:
        """Phase 3: 并行盲评终判。
        单个 reviewer 失败时降级为低置信度 Verdict,不击溃整批。"""
        def work(idx: int) -> Verdict:
            try:
                return self._blind_final(
                    reviewers[idx], content, current_positions[idx], context
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"Reviewer '{reviewers[idx].name}' failed in blind final: {e}"
                )
                return Verdict(
                    severity=Severity.MAJOR,
                    confidence=0.0,
                    reasoning=f"[REVIEWER FAILED: {e}]",
                    findings=[],
                    satisfied=False,
                )

        results: list[Verdict | None] = [None] * len(reviewers)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_idx = {
                pool.submit(work, i): i for i in range(len(reviewers))
            }
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                results[idx] = fut.result()
        return [r for r in results if r is not None]

    def _independent_review(
        self, reviewer: ReviewerConfig, content: str, context: str | None
    ) -> Verdict:
        """独立评审。内部支持 majority_vote (G-5): 同模型多次调用 + 投票。"""
        llm = self.broker.get_llm(reviewer.model)
        user_prompt = self._build_user_prompt(content, reviewer.checklist, context)

        if reviewer.majority_vote > 1:
            # 多数投票模式: 调用 N 次,投票聚合
            return run_majority_vote(
                llm, reviewer, user_prompt, votes=reviewer.majority_vote
            )
        else:
            response = llm.complete(
                reviewer.system_prompt, user_prompt,
                temperature=reviewer.temperature,
            )
            return parse_verdict(response)

    def _debate_round(
        self, reviewers, content, current_positions, context
    ) -> list[str]:
        """Phase 2: 一轮辩论。各 reviewer 看到其他人的观点后反驳。
        单个 reviewer 辩论失败时保留原立场,不击溃整批。"""
        round_arguments: list[str | None] = [None] * len(reviewers)

        def work(i: int) -> str:
            reviewer = reviewers[i]
            others = "\n".join(
                f"[{reviewers[j].name}]: {current_positions[j]}"
                for j in range(len(reviewers)) if j != i
            )
            try:
                return self._debate_single(reviewer, content, others, context)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"Reviewer '{reviewer.name}' failed in debate round: {e}"
                )
                return current_positions[i]  # 保留原立场

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_idx = {pool.submit(work, i): i for i in range(len(reviewers))}
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                round_arguments[idx] = fut.result()
        return [a for a in round_arguments if a is not None]

    def _debate_single(
        self, reviewer: ReviewerConfig, content: str, others_args: str, context: str | None
    ) -> str:
        llm = self.broker.get_llm(reviewer.model)
        system = reviewer.system_prompt + (
            "\n\n你现在进入辩论阶段。其他审查者的观点如下,"
            "请挑战你不同意的部分,坚持你有证据的部分:\n"
        )
        user = (
            f"被审查内容:\n{content}\n\n"
            f"其他审查者观点:\n{others_args}\n\n"
            f"你的反驳:"
        )
        return llm.complete(system, user, temperature=reviewer.temperature)

    def _blind_final(
        self, reviewer: ReviewerConfig, content: str, debated_position: str, context: str | None
    ) -> Verdict:
        llm = self.broker.get_llm(reviewer.model)
        system = reviewer.system_prompt + "\n\n辩论已结束。请基于辩论中的所有信息,给出你的最终裁决。"
        user = (
            f"被审查内容:\n{content}\n\n"
            f"辩论后你的立场:\n{debated_position}\n\n"
            f"请给出最终裁决(严重程度/置信度/依据/建议):"
        )
        response = llm.complete(system, user, temperature=reviewer.temperature)
        return parse_verdict(response)

    def _synthesize(
        self, verdicts: list[Verdict], reviewers: list[ReviewerConfig], content: str
    ) -> Verdict:
        """加权聚合各 reviewer 的终审判定。
        (B-1): 使用 Severity.rank 排序,而非字符串 max()。"""
        total_weight = sum(r.weight for r in reviewers)
        weighted_confidence = sum(
            v.confidence * r.weight for v, r in zip(verdicts, reviewers)
        ) / total_weight

        # (B-1 修正) 最严判定: 用 Severity.rank 比较,取 rank 最高的
        max_severity = max(verdicts, key=lambda v: v.severity.rank).severity

        all_findings = [f for v in verdicts for f in v.findings]

        # satisfied = 所有人都判 pass
        all_satisfied = all(v.severity == Severity.PASS for v in verdicts)

        return Verdict(
            severity=max_severity,
            confidence=round(weighted_confidence, 4),
            reasoning="\n---\n".join(v.reasoning for v in verdicts),
            findings=all_findings,
            satisfied=all_satisfied,
            original_content=content,    # (L-3) 填充 original_content
        )

    def _build_user_prompt(
        self, content: str, checklist, context: str | None
    ) -> str:
        checklist_text = "\n".join(f"  - {c.criteria}" for c in checklist)
        parts = [
            f"# 被审查内容\n{content}",
            f"\n# 检查清单\n{checklist_text}",
        ]
        if context:
            parts.append(f"\n# 背景上下文\n{context}")
        parts.append(
            "\n# 输出要求\n"
            "请用 ```json 代码块返回结构化裁决,包含:\n"
            "- severity: critical / major / minor / pass\n"
            "- confidence: 0.0-1.0\n"
            "- reasoning: 推理过程\n"
            "- findings: [{description, severity, confidence, evidence, suggestion}]\n"
            "- satisfied: bool"
        )
        return "\n".join(parts)
```

```python
# src/adversarial_judge/consensus.py (新建, M-5)
from .types import Verdict

def compute_consensus(verdicts: list[Verdict]) -> float:
    """共识度 = reviewer 在 satisfied 判定上的一致比例。
    1.0 = 完全一致(所有人判 satisfied 或所有人判 unsatisfied),
    0.0 = 完全分歧(一半对一半)。
    用 2×|ratio - 0.5| 映射到 [0,1]: 3/4 → 0.5, 4/4 → 1.0, 2/4 → 0.0。"""
    if not verdicts:
        return 0.0
    satisfied_count = sum(1 for v in verdicts if v.satisfied)
    total = len(verdicts)
    ratio = satisfied_count / total
    # 2 × |ratio - 0.5|: ratio=1.0→1.0, ratio=0.75→0.5, ratio=0.5→0.0, ratio=0.0→1.0
    return round(2 * abs(ratio - 0.5), 4)

def compute_stability(
    individual: list[Verdict], final: list[Verdict]
) -> float:
    """稳定性 = 辩论前后 satisfied 判定未翻转的比例。
    1.0 = 所有 reviewer 立场未变, 0.0 = 全部翻转。"""
    if not individual or not final:
        return 1.0
    unchanged = sum(
        1 for i, f in zip(individual, final) if i.satisfied == f.satisfied
    )
    return round(unchanged / len(individual), 4)
```

### 4.5 改造5: 置信度评分 + 人工升级路由 + 结构化输出

> **关键修正**:
> - (B-5) `parse_verdict` 实现多级降级: JSON 代码块 → 裸 JSON → `<SATISFIED>` 标签
> - (M-6) 统一使用 `Severity` 枚举,`Finding` 不允许 `pass`
> - (G-5) `run_majority_vote` 保留 AaaJ 原始投票+置信度算法

```python
# src/adversarial_judge/judge.py
import json
import re
from .types import Verdict, Finding, Severity
from .reviewer import ReviewerConfig
from pydantic import ValidationError

def parse_verdict(response: str) -> Verdict:
    """从 LLM 响应解析结构化裁决 (B-5: 多级降级)。
    1. ```json ... ``` 代码块
    2. 裸 JSON 对象(第一个 {...})
    3. <SATISFIED>/<UNSATISFIED> 标签降级(AaaJ 原方案, confidence capped 0.5)
    """
    # Level 1: JSON 代码块
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return _build_verdict(data)
        except (json.JSONDecodeError, ValidationError, ValueError):
            pass

    # Level 2: 裸 JSON
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return _build_verdict(data)
        except (json.JSONDecodeError, ValidationError, ValueError):
            pass

    # Level 3: 标签降级(AaaJ 原方案)
    if "<SATISFIED>" in response:
        return Verdict(
            severity=Severity.PASS,
            confidence=0.5,  # 标签降级时置信度 capped 0.5(低置信度,触发人工)
            reasoning=response,
            findings=[],
            satisfied=True,
        )
    elif "<UNSATISFIED>" in response:
        return Verdict(
            severity=Severity.MAJOR,  # 默认 major
            confidence=0.5,
            reasoning=response,
            findings=[],
            satisfied=False,
        )

    raise ValueError(f"Could not parse verdict from response: {response[:200]}...")

def _build_verdict(data: dict) -> Verdict:
    """从 dict 构建 Verdict,做字段适配。"""
    # 适配 findings 中的 severity 字段(可能为字符串)
    findings_data = data.get("findings", [])
    findings = []
    for f in findings_data:
        severity_val = f.get("severity", "minor")
        # 跳过 pass 级别的 finding (M-6); 大小写不敏感
        if str(severity_val).lower() == "pass":
            continue
        try:
            sev = Severity(str(severity_val).lower())
        except ValueError:
            sev = Severity.MINOR  # 未知 severity 降级为 minor
        if sev == Severity.PASS:
            continue
        findings.append(Finding(
            description=f.get("description", ""),
            severity=sev,
            confidence=float(f.get("confidence", 0.5)),
            evidence=f.get("evidence", ""),
            suggestion=f.get("suggestion", ""),
        ))

    severity_val = data.get("severity", "minor")
    try:
        sev = Severity(str(severity_val).lower())
    except ValueError:
        sev = Severity.MINOR  # 未知 severity 降级为 minor

    # 提取 confidence_adjustment (元审查者输出的校准建议)
    confidence_adjustment = data.get("confidence_adjustment")
    if confidence_adjustment is not None:
        try:
            confidence_adjustment = float(confidence_adjustment)
        except (TypeError, ValueError):
            confidence_adjustment = None

    return Verdict(
        severity=sev,
        confidence=float(data.get("confidence", 0.5)),
        reasoning=data.get("reasoning", ""),
        findings=findings,
        satisfied=bool(data.get("satisfied", sev == Severity.PASS)),
        confidence_adjustment=confidence_adjustment,
    )

def run_majority_vote(
    llm, reviewer: ReviewerConfig, user_prompt: str, votes: int
) -> Verdict:
    """同模型多次调用 + 投票聚合 (G-5: 保留 AaaJ 原始算法)。
    复用 DevAsk.check() 的 majority_vote + satisfied_ratio + confidence 算法。"""
    responses = []
    verdicts = []
    for _ in range(votes):
        response = llm.complete(
            reviewer.system_prompt, user_prompt,
            temperature=reviewer.temperature,
        )
        responses.append(response)
        verdicts.append(parse_verdict(response))

    # 投票: satisfied 的比例
    satisfied_count = sum(1 for v in verdicts if v.satisfied)
    total = len(verdicts)
    satisfied_ratio = satisfied_count / total if total else 0.0
    majority_satisfied = satisfied_ratio >= 0.5

    # (AaaJ 原始公式) confidence = max(satisfied_ratio, 1 - satisfied_ratio)
    confidence = max(satisfied_ratio, 1.0 - satisfied_ratio)

    # 合并 findings
    all_findings = [f for v in verdicts for f in v.findings]

    # 最严 severity
    max_severity = max(verdicts, key=lambda v: v.severity.rank).severity

    return Verdict(
        severity=max_severity,
        confidence=round(confidence, 4),
        reasoning="\n---\n".join(v.reasoning for v in verdicts),
        findings=all_findings,
        satisfied=majority_satisfied,
    )
```

```python
# src/adversarial_judge/escalation.py
from .types import Verdict

class EscalationRouter:
    """置信度阈值 → 人工升级路由。"""
    def __init__(self, confidence_threshold: float = 0.8):
        self.threshold = confidence_threshold

    def should_escalate(self, verdict: Verdict) -> bool:
        """置信度低于阈值 → 标记需要人工介入。
        若经过元审查,使用 calibrated_confidence;否则使用原始 confidence。"""
        effective = (
            verdict.calibrated_confidence
            if verdict.calibrated_confidence is not None
            else verdict.confidence
        )
        return effective < self.threshold

    def annotate(self, verdict: Verdict) -> Verdict:
        verdict.escalate_to_human = self.should_escalate(verdict)
        return verdict
```

### 4.6 改造6: 元审查(审查结果可被审查)

> **关键修正**:
> - (B-3) 元审查使用**至少 2 个 meta-reviewer**(不同模型/视角),形成真正对抗
> - (B-4) 校准通过**显式公式**实现,非简单覆盖元审查者 confidence
> - 元审查在架构上几乎免费——`DebateOrchestrator.run(content: str, ...)` 接受任意文本,`Verdict` 序列化成文本后就是 `content`

```python
# src/adversarial_judge/meta_review.py
import json
from .debate import DebateOrchestrator, DebateResult
from .types import Verdict, Severity

class MetaReviewer:
    """对审查结果进行再次审查,校准置信度。
    (B-3): 使用至少 2 个 meta-reviewer 形成对抗。"""

    DEFAULT_META_REVIEWERS = ["meta-reviewer", "meta-reviewer-2"]

    def __init__(self, orchestrator: DebateOrchestrator, meta_reviewer_names: list[str] | None = None):
        self.orchestrator = orchestrator
        self.meta_reviewer_names = meta_reviewer_names or self.DEFAULT_META_REVIEWERS

    def review(
        self,
        original_content: str,            # 原始被审查内容
        original_verdict: Verdict,        # 一级审查的裁决
    ) -> tuple[Verdict, DebateResult]:
        """返回 (校准后的verdict, 元审查debate结果)"""

        # 将 Verdict 序列化为文本,作为元审查的 content
        verdict_text = self._serialize_verdict(original_verdict, original_content)

        # (B-3) 用多个 meta-reviewer 跑辩论(通常 debate_rounds=1 即可)
        meta_result = self.orchestrator.run(
            content=verdict_text,
            reviewer_names=self.meta_reviewer_names,
            context=original_content,      # 原始内容作为上下文,供回溯验证 evidence
        )

        # (B-4) 显式校准公式
        calibrated = self._calibrate_confidence(original_verdict, meta_result.final_verdict)
        original_verdict.calibrated_confidence = calibrated
        return original_verdict, meta_result

    def _calibrate_confidence(
        self,
        original_verdict: Verdict,
        meta_verdict: Verdict,
    ) -> float:
        """(B-4) 显式校准公式。

        策略: 基于元审查发现的严重程度扣减原始置信度。

        calibrated = original_confidence × (1 - meta_penalty)

        其中 meta_penalty 根据元审查发现的最严重 severity 计算:
        - critical → penalty = 0.5 (严重漏判/过判,大幅下调)
        - major    → penalty = 0.3
        - minor    → penalty = 0.1
        - pass     → penalty = 0.0 (元审查未发现问题,保持原始值)

        若 meta_verdict 有 confidence_adjustment 字段(元审查者显式建议),
        则结合使用: calibrated = clamp(original + adjustment, 0, 1) × (1 - meta_penalty/2)
        """
        original = original_verdict.confidence

        # 基于元审查 severity 的扣减
        severity_penalty = {
            Severity.CRITICAL: 0.5,
            Severity.MAJOR: 0.3,
            Severity.MINOR: 0.1,
            Severity.PASS: 0.0,
        }
        penalty = severity_penalty.get(meta_verdict.severity, 0.0)

        calibrated = original * (1.0 - penalty)

        # 若元审查者给出显式调整量,加权融合
        if meta_verdict.confidence_adjustment is not None:
            adjustment = meta_verdict.confidence_adjustment
            adjusted = max(0.0, min(1.0, original + adjustment))
            calibrated = (calibrated + adjusted) / 2.0

        return round(max(0.0, min(1.0, calibrated)), 4)

    def _serialize_verdict(self, verdict: Verdict, original_content: str) -> str:
        findings_text = "\n".join(
            f"  - [{f.severity.value}] {f.description} (置信度:{f.confidence})\n"
            f"    依据: {f.evidence}\n"
            f"    建议: {f.suggestion}"
            for f in verdict.findings
        )
        return (
            f"# 原始被审查内容\n{original_content}\n\n"
            f"# 审查报告(Verdict)\n"
            f"整体严重程度: {verdict.severity.value}\n"
            f"置信度: {verdict.confidence}\n"
            f"通过: {verdict.satisfied}\n"
            f"推理: {verdict.reasoning}\n\n"
            f"发现列表:\n{findings_text}\n\n"
            f"# 你的任务\n"
            f"作为元审查者,请判断上述审查报告是否可信。"
            f"输出 confidence_adjustment (-1.0 ~ +1.0) 表示对原始置信度的调整建议。"
        )
```

### 4.7 改造7: 通用 CLI(提示词传递内容,不依赖文件路径)

> **关键修正**:
> - (B-2) `review_depth` 默认 0(不元审查);`--meta-review` 等价于 `--review-depth 1`
> - (M-7) JSON 输出到 stdout 或文件,**不到 stderr**;`--output both` 写两个文件
> - (M-4) 新增 `--override-model` 强制覆盖所有 reviewer 的 model
> - (FR-5) 新增 `--interactive` 模式:低置信度时暂停等 stdin 人工裁决
> - (NFR-2) 新增 `--max-cost` 预算控制

```python
# src/adversarial_judge/cli.py
import typer
from pathlib import Path
from typing import Optional
import sys, os, json

app = typer.Typer()

@app.command()
def review(
    content: Optional[str] = typer.Option(None, "--content", "-c", help="被审查内容(直接传入文本)"),
    content_file: Optional[Path] = typer.Option(None, "--file", "-f", help="从文件读取被审查内容(.json 自动提取 verdict 字段)"),
    context: Optional[str] = typer.Option(None, "--context", help="背景上下文(需求文档/设计文档等)"),
    profile: Optional[str] = typer.Option(None, "--profile", help="预设档位: fast/standard/thorough。不指定且无细粒度参数时走 auto 路由(4.8)"),
    reviewers: list[str] = typer.Option(None, "--reviewer", "-r", help="指定使用的 reviewer 名称(可多次,显式指定时覆盖 auto 路由)"),
    reviewers_dir: Path = typer.Option(Path("reviewers"), "--reviewers-dir", help="reviewer 定义目录"),
    output_format: str = typer.Option("markdown", "--output", "-o", help="输出格式: markdown/json/both"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="输出目录(--output both 时必须)"),
    confidence_threshold: float = typer.Option(0.8, "--threshold", "-t", help="置信度阈值,低于此值标记人工审查"),
    debate_rounds: Optional[int] = typer.Option(None, "--debate-rounds", help="辩论轮次(不指定时由 profile/auto 决定)"),
    model: str = typer.Option("anthropic/claude-sonnet-4-20250514", "--model", help="默认 LLM 模型(reviewer 未指定 model 时使用)"),
    override_model: Optional[str] = typer.Option(None, "--override-model", help="强制覆盖所有 reviewer 的 model(用于测试)"),
    meta_review: bool = typer.Option(False, "--meta-review", help="启用元审查(等价于 --review-depth 1)"),
    review_depth: Optional[int] = typer.Option(None, "--review-depth", help="元审查递归深度(默认由 profile 决定,硬上限2)"),
    max_cost: Optional[float] = typer.Option(None, "--max-cost", help="预算上限(USD),超限终止"),
    interactive: bool = typer.Option(False, "--interactive", help="低置信度时暂停等待 stdin 人工裁决"),
):
    """对抗审查: 对 AI 生成的内容进行多 agent 辩论式审查"""

    # (B-2) review_depth 硬上限校验
    if review_depth is not None and review_depth > 2:
        typer.echo("Error: --review-depth 上限为 2", err=True)
        raise typer.Exit(1)
    # --meta-review 等价于 --review-depth 1
    if meta_review:
        review_depth = max(review_depth or 0, 1)

    # (L-4) --file 支持 .json 后缀: 自动提取 verdict 字段
    if content:
        review_content = content
    elif content_file:
        raw = content_file.read_text(encoding="utf-8")
        if content_file.suffix == ".json":
            try:
                data = json.loads(raw)
                # 尝试提取 verdict 相关字段作为文本
                review_content = data.get("reasoning") or data.get("verdict", {}).get("reasoning") or raw
            except json.JSONDecodeError:
                review_content = raw
        else:
            review_content = raw
    else:
        review_content = sys.stdin.read()

    if not review_content.strip():
        typer.echo("Error: 无审查内容。请通过 --content / --file / stdin 传入。", err=True)
        raise typer.Exit(1)

    # 加载 reviewer 配置
    from .reviewer import ReviewerRegistry
    registry = ReviewerRegistry(reviewers_dir)

    # (4.8) 流程决策: 显式细粒度参数 > --profile > auto 路由
    from .router import route, PROFILE_MAP
    route_decision = None
    if reviewers is None or debate_rounds is None or review_depth is None:
        if profile is not None:
            # 半决策: 显式档位,跳过路由
            settings = PROFILE_MAP[profile]
            route_decision = {"profile": profile, **settings, "reason": f"explicit profile: {profile}"}
        else:
            # 零决策: auto 路由(一次轻量 LLM 分类)
            from .llm.broker import LLMBroker as _B
            _broker_tmp = _B(default_model=model, default_api_key=os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))
            route_decision = route(_broker_tmp, review_content, [r.name for r in registry.list_all() if not r.name.startswith("meta-")])
            settings = PROFILE_MAP[route_decision.profile]
            typer.echo(f"auto 路由: {route_decision.profile} 档, reviewer={route_decision.reviewer_names}, 理由: {route_decision.reason}", err=True)
        if reviewers is None:
            reviewers = route_decision.get("reviewer_names") or route_decision.reviewer_names
        if debate_rounds is None:
            debate_rounds = route_decision.get("debate_rounds") if isinstance(route_decision, dict) else settings["debate_rounds"]
        if review_depth is None:
            review_depth = settings["meta_review"] and 1 or 0
    typer.echo(f"使用 reviewer: {reviewers}", err=True)

    # 初始化 LLM broker (M-4: 支持 override_model)
    from .llm.broker import LLMBroker
    effective_model = override_model or model
    broker = LLMBroker(
        default_model=effective_model,
        default_api_key=os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"),
        max_budget_usd=max_cost,
    )

    # (M-4) 若 override_model,覆盖所有 reviewer 的 model
    if override_model:
        for r_config in registry.list_all():
            r_config.model = override_model

    # 运行辩论
    from .debate import DebateOrchestrator
    orchestrator = DebateOrchestrator(
        registry=registry,
        broker=broker,
        debate_rounds=debate_rounds,
    )
    result = orchestrator.run(content=review_content, reviewer_names=reviewers, context=context)

    # 预算检查(执行中已由 broker.check_budget() 在各 Phase 间检查并提前终止)
    if not broker.check_budget():
        typer.echo(
            f"Warning: 预算超限 (${broker.get_total_cost():.4f} >= ${max_cost}),"
            f"部分阶段可能已跳过", err=True
        )

    # 元审查(若启用, D-12: 多 meta-reviewer)
    from .meta_review import MetaReviewer
    from .escalation import EscalationRouter
    meta_result = None
    current_depth = 0
    while current_depth < review_depth:
        meta_reviewer_obj = MetaReviewer(orchestrator)
        result.final_verdict, meta_result = meta_reviewer_obj.review(
            original_content=review_content,
            original_verdict=result.final_verdict,
        )
        current_depth += 1
        # 元审查用原始内容作为下一轮的"原始内容"
        review_content = result.final_verdict.reasoning

    # 置信度升级路由
    router = EscalationRouter(confidence_threshold=confidence_threshold)
    result.final_verdict = router.annotate(result.final_verdict)

    # (FR-5) interactive 模式:低置信度时暂停等待人工裁决
    if interactive and result.final_verdict.escalate_to_human:
        typer.echo(
            f"\n⚠️  置信度 {result.final_verdict.calibrated_confidence or result.final_verdict.confidence} "
            f"低于阈值 {confidence_threshold},需要人工介入。\n"
            f"请输入人工裁决 (pass/fail + 备注), 或按 Enter 跳过:",
            err=True,
        )
        human_input = sys.stdin.readline().strip()
        if human_input:
            typer.echo(f"人工裁决已记录: {human_input}", err=True)
            # 将人工裁决附加到 verdict
            result.final_verdict.reasoning += f"\n\n[人工裁决]: {human_input}"

    # 输出 (M-7: JSON 不到 stderr)
    from .output.markdown_report import render_markdown
    from .output.json_verdict import render_json

    if output_format == "markdown":
        md = render_markdown(result, confidence_threshold, meta_result)
        print(md)
    elif output_format == "json":
        json_out = render_json(result, confidence_threshold, meta_result, broker)
        print(json_out)
    elif output_format == "both":
        if not output_dir:
            typer.echo("Error: --output both 需要 --output-dir", err=True)
            raise typer.Exit(1)
        output_dir.mkdir(parents=True, exist_ok=True)
        md = render_markdown(result, confidence_threshold, meta_result)
        json_out = render_json(result, confidence_threshold, meta_result, broker)
        (output_dir / "report.md").write_text(md, encoding="utf-8")
        (output_dir / "verdict.json").write_text(json_out, encoding="utf-8")
        typer.echo(f"报告已写入: {output_dir / 'report.md'}", err=True)
        typer.echo(f"JSON 已写入: {output_dir / 'verdict.json'}", err=True)

@app.command()
def list_reviewers(
    reviewers_dir: Path = typer.Option(Path("reviewers"), "--reviewers-dir"),
):
    """列出所有可用的 reviewer"""
    from .reviewer import ReviewerRegistry
    registry = ReviewerRegistry(reviewers_dir)
    for r in registry.list_all():
        model_str = r.model or "(用默认模型)"
        typer.echo(f"  {r.name:40s} [{model_str}]  {r.description}")

if __name__ == "__main__":
    app()
```

### 4.8 改造8: 流程决策自动化(借鉴 LangGraph supervisor 路由 + CyberAgent 零参数体验)

> **设计原则修正**: 原则不再是"LLM 对流程零决定权",而是 **"LLM 仅在入口做一次路由决策(temperature=0,可审计、可复现),流程主体是确定性管线"**——这是 LangGraph supervisor 的标准模式(LLM 路由分派 + 确定性执行),也对标 CyberAgent 的零参数全自动体验(用户触发即跑,验证方式 judge 自主决定)。

#### 4.8.1 三层决策模型

| 层 | 决策者 | 机制 | 成本 | 业界对标 |
|---|---|---|---|---|
| **L1 入口路由**(默认 auto) | 一次轻量 LLM 分类 | 判定内容类型 + 复杂度 → 自动选档位 + 自动选 reviewer 组合 | ~1 次轻量调用(便宜模型,temp=0,几百 token) | LangGraph supervisor 路由;CyberAgent judge 自主决定验证方式 |
| **L0 规则自动**(流程主体) | 系统代码(确定性) | 见 4.8.2 | 零 | LangGraph 确定性执行 |
| **L2 人工覆盖**(可选) | 用户 CLI 参数 | `--profile` 或细粒度参数 | 零 | agent-review-panel 固定流程 |

**决策流向**: CLI 入口 → (无显式参数时)L1 路由选定档位与 reviewer 组合 → L0 规则在执行中自动跳过/短路 → 全程用户零决策。

#### 4.8.2 L0 规则自动清单(全部确定性代码,可复现)

| 规则 | 触发条件 | 动作 |
|---|---|---|
| 跳过 Phase 2(辩论) | reviewer 数 < 2 | 无对手,物理不可辩论 |
| **跳过 Phase 3(盲评)** | 单 reviewer(快检形态) | 复核者=初判者,自检无增量价值;Phase 1 结果直接进合成;`stability_score` 记 `degraded=true` 诚实标注 |
| 抗随机替代 | reviewer 模板 `majority_vote ≥ 2` | 多次独立采样投票 > 自我反思(AaaJ 论文结论) |
| 辩论中途短路 | `--max-cost` 预算超限 | 跳到 Phase 4 用已有结果合成 |
| 元审查开关 | `--review-depth`(默认 0) | 规则控制递归深度(硬上限 2) |
| 升级人工 | calibrated_confidence < 阈值 | 标注 `escalate_to_human`(数字比较) |

#### 4.8.3 Profile 档位(L1 路由的目标)

| 档位 | reviewer 数 | 辩论轮 | 元审查 | LLM 调用数 | 适用场景 |
|---|---|---|---|---|---|
| **fast** | 1 | 0 | 否 | **1** | 短文本快检、CI 门禁、迭代内自检 |
| **standard** | 2 | 1 | 否 | ~6 | 常规文档审查(默认产出质量档) |
| **thorough** | 3 | 2 | 是 | ~15 | 关键交付物、复杂多维度内容、终审 |

#### 4.8.4 auto 路由器(router.py)

```python
# src/adversarial_judge/router.py (新建)
from pydantic import BaseModel
from .llm.broker import LLMBroker

class RouteDecision(BaseModel):
    content_type: str          # requirement / spec / design / code / test / agent_log / review_report / other
    complexity: str            # low / medium / high
    profile: str               # fast / standard / thorough
    reviewer_names: list[str]  # 自动选择的 reviewer 组合
    reason: str                # 路由理由(可审计)

ROUTER_SYSTEM_PROMPT = """你是审查流程路由器。分析输入内容的类型与复杂度,返回 JSON:
{content_type, complexity, profile, reviewer_names, reason}。
规则:
- 短文本(<500字)/单一维度 → fast; 常规文档 → standard; 长文档/多维度/关键交付 → thorough
- reviewer_names 从可用列表中选择与内容类型匹配的组合(每档 1/2/3 个)
- 只输出 JSON"""

PROFILE_MAP = {
    "fast": {"reviewers": 1, "debate_rounds": 0, "meta_review": False},
    "standard": {"reviewers": 2, "debate_rounds": 1, "meta_review": False},
    "thorough": {"reviewers": 3, "debate_rounds": 2, "meta_review": True},
}

def route(broker: LLMBroker, content: str, available_reviewers: list[str]) -> RouteDecision:
    """入口路由: 一次轻量 LLM 分类调用(便宜模型, temp=0)。
    决定档位 + reviewer 组合; 流程主体仍由 L0 规则确定性执行。"""
    llm = broker.get_llm()  # 用默认模型,或路由专用便宜模型
    user = f"可用 reviewer: {[r for r in available_reviewers]}\n\n内容(截断):\n{content[:2000]}"
    response = llm.complete(ROUTER_SYSTEM_PROMPT, user, temperature=0.0)
    decision = _parse_route(response)  # 多级降级解析(同 parse_verdict 模式)
    # 兜底: 解析失败 → standard 档 + 通用 reviewer 组合(规则降级,非报错)
    return decision
```

**设计要点**:
- 路由调用 temperature=0,输出含 `reason` 字段可审计
- **解析失败兜底为 standard 档**(规则降级),不报错——路由是优化不是依赖
- 路由结果与后续流程在 JSON verdict 的 `route` 字段中完整记录(可追溯"为什么走了这个档位")

#### 4.8.5 用户体验三档

```bash
# 零决策(默认, 对标 CyberAgent):
aj review --file spec.md                        # auto: 路由自动选档位 + reviewer 组合

# 半决策(对标 agent-review-panel):
aj review --file spec.md --profile fast         # 显式档位,跳过路由

# 全决策(高级用户,细粒度覆盖):
aj review --file spec.md -r spec-reviewer -r design-reviewer \
  --debate-rounds 2 --meta-review --max-cost 0.5
```

---

## 5. 元审查设计详解

### 5.1 元审查的价值

元审查不只是"再查一遍",核心价值是**校准原始审查的置信度**:
- 原始审查 confidence=0.9 但 meta-reviewer 发现漏判 → calibrated_confidence 降到 0.45 (0.9 × (1-0.5)) → 触发人工升级
- 原始审查 confidence=0.6 但 meta-reviewer 确认证据充分 → calibrated_confidence 升到 0.85 (若 adjustment=+0.25, (0.6×1.0 + 0.85)/2) → 无需人工

### 5.2 元审查的输入

| 输入 | 来源 | 用途 |
|---|---|---|
| 原始被审查内容 | 一级审查的 `content` | 作为 `context` 传给 meta-reviewer,供回溯验证 evidence 真实性 |
| 原始 Verdict | 一级审查的输出 | 序列化为文本作为元审查的 `content` |

### 5.3 防止无限递归

`--review-depth N` 控制递归深度(硬上限 2,超过报错):
- `0`(默认): 仅一级审查,不元审查
- `1`(`--meta-review` 快捷方式): 一级 + 元审查,平衡成本与可靠性
- `2`: 一级 + 元审查 + 元元审查(极少需要,成本翻 3 倍)

### 5.4 校准公式 (B-4 修正)

元审查不直接覆盖原始 confidence,而是通过**显式公式**校准:

```
calibrated = original_confidence × (1 - meta_penalty)
```

`meta_penalty` 根据元审查发现的最严重 severity:

| 元审查 severity | penalty | 含义 |
|---|---|---|
| critical | 0.5 | 严重漏判/过判,大幅下调 |
| major | 0.3 | 显著问题,中度下调 |
| minor | 0.1 | 轻微问题,小幅下调 |
| pass | 0.0 | 元审查未发现问题,保持原始值 |

若元审查者给出显式 `confidence_adjustment` 字段(-1.0 ~ +1.0):
```
adjusted = clamp(original + adjustment, 0, 1)
calibrated = (calibrated + adjusted) / 2
```

### 5.5 元审查的 reviewer

元审查使用**至少 2 个 meta-reviewer**(不同模型/视角),形成真正对抗:

| reviewer | 模型 | 视角 |
|---|---|---|
| `meta-reviewer` | Claude sonnet | 漏判/过判/置信度失准/推理缺口/共识假象 + 完整性审计 |
| `meta-reviewer-2` | GPT-4o (异构) | 推理链断裂/隐含假设未验证 + 完整性审计 |

`meta-reviewer.yaml` 的 6 个审查维度:
1. **漏判**: 原始内容中有明显问题,但审查报告未发现
2. **过判**: 审查报告标记的问题其实不成立或被夸大
3. **置信度失准**: confidence 与实际证据强度不匹配
4. **推理缺口**: findings 的 evidence 不能支撑其 severity
5. **共识假象**: 多 reviewer "共识"实为互相附和,非独立验证
6. **完整性审计**(借鉴 agent-review-panel): 审查报告是否覆盖了原始内容的所有关键维度

---

## 6. 与 Claude / OpenCode 的集成

### 6.1 LLM 后端: litellm → Anthropic API

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
aj review --content "..." --model anthropic/claude-sonnet-4-20250514
```

litellm 通过 model string 前缀路由到 Anthropic,`api_key` 参数通用。

### 6.2 接入方式: 仅 CLI 管道

> **设计决策**(1.5 节):对外只暴露 CLI 管道方式。不支持 Stop hook(Python 库嵌入)。

```bash
# Claude Code 产出的需求文档,管道传入审查
claude-code generate-requirements.md | aj review -r requirement-elicitation-reviewer --debate-rounds 2

# OpenCode 产出的设计文档
opencode design-output | aj review -r design-reviewer -o json > verdict.json

# 审查 Claude Code 的代码检视报告
cat pr-review.md | aj review -r external-code-review-auditor

# CI/CD 中嵌入审查结果
aj review --file ./spec.md -r spec-reviewer -o json | jq '.verdict.escalate_to_human'
```

### 6.3 多模型混用示例

```yaml
# reviewers/requirement_elicitation_reviewer.yaml
model: anthropic/claude-sonnet-4-20250514    # 主力

# reviewers/spec_reviewer.yaml
model: anthropic/claude-opus-4-20250514      # 更深推理

# reviewers/meta_reviewer_2.yaml
model: openai/gpt-4o                          # 异构模型,避免同模型盲区
```

```bash
# CLI 强制覆盖所有 reviewer 的 model(测试用)
aj review --file ./spec.md -r spec-reviewer --override-model openai/gpt-4o
```

---

## 7. CLI 接口设计

### 7.1 命令

| 命令 | 用途 |
|---|---|
| `aj review` | 执行对抗审查(主命令) |
| `aj list-reviewers` | 列出所有可用 reviewer(含模型信息) |

### 7.2 使用示例

```bash
# 0. 零决策全自动(默认推荐,对标 CyberAgent 体验):
#    auto 路由自动判定档位 + reviewer 组合,全程无参数
aj review --file ./spec.md

# 0b. 半决策:显式选档
aj review --file ./spec.md --profile fast      # 快检(1次调用)
aj review --file ./spec.md --profile thorough  # 深审(3 reviewer + 2轮辩论 + 元审查)

# 1. 直接传入文本审查需求收集文档(全决策,细粒度覆盖)
aj review --content "我们的系统需要支持高并发..." \
  --reviewer requirement-elicitation-reviewer \
  --reviewer spec-reviewer \
  --threshold 0.8 \
  --debate-rounds 2

# 2. 从文件审查规格文档
aj review --file ./spec.md \
  --reviewer spec-reviewer \
  --reviewer design-reviewer \
  --output json

# 3. 管道(与其他工具集成)
cat requirements.md | aj review -r requirement-elicitation-reviewer --debate-rounds 3

# 4. 元审查: 审查上一轮的审查结果
aj review --file verdict.json --meta-review -o json > meta_verdict.json

# 5. 双格式输出到目录
aj review --file ./spec.md -r spec-reviewer --output both --output-dir ./reports

# 6. 预算控制 + 强制覆盖模型(测试用)
aj review --file ./spec.md -r spec-reviewer --override-model openai/gpt-4o --max-cost 0.50

# 7. interactive 模式: 低置信度时暂停等人工输入
aj review --file ./spec.md -r spec-reviewer --interactive

# 8. 多数投票模式(轻量级反幻觉,不跑辩论)
aj review --file ./spec.md -r spec-reviewer --debate-rounds 0
# (reviewer YAML 中设置 majority_vote: 3)

# 9. 列出可用 reviewer
aj list-reviewers
```

### 7.3 输出示例(JSON)

```json
{
  "verdict": {
    "severity": "major",
    "confidence": 0.65,
    "calibrated_confidence": 0.455,
    "escalate_to_human": true,
    "satisfied": false,
    "findings": [
      {
        "description": "需求未定义并发量级",
        "severity": "major",
        "confidence": 0.72,
        "evidence": "原文:'支持高并发'未量化",
        "suggestion": "明确 QPS 目标(如 10000 QPS)"
      }
    ],
    "reasoning": "requirement-elicitation-reviewer 与 spec-reviewer 在辩论后达成共识..."
  },
  "individual_verdicts": [...],
  "final_verdicts": [...],
  "debate_rounds": [[...], [...]],
  "consensus_score": 0.75,
  "stability_score": 1.0,
  "meta_review": {...},
  "cost": {"total_tokens": 15420, "total_cost_usd": 0.12}
}
```

---

## 8. 实施路线图

> 详细实施计划见 [plan.md](./plan.md)。以下为概要。

| 阶段 | 工作量 | 交付物 |
|---|---|---|
| Phase 0: 文档修正 | 0.5天 | 修正 spec.md (G-1~G-4) + design.md (B-1~B-5, M-1~M-8) |
| Phase 1: Fork + 精简 | 1.5天 | 删除证据收集模块 + benchmark + scripts,保留 litellm + Cost + DevAsk 算法 + judge prompt,pyproject 精简,包名迁移 |
| Phase 2: 多模型注入 | 1.5天 | LLM 类改为 DI(保留 Cost + retry),LLMBroker 管理多模型实例 + 预算控制,structured_output tool-use + 降级 |
| Phase 3: 外部 reviewer 定义 | 2天 | ReviewerConfig(model Optional + majority_vote) + YAML 格式 + Registry + 13 个视角模板(含 3 个过程级: 过程合规/欺骗检测/危险操作) |
| Phase 4: 辩论编排器 + auto 路由 | 3.5天 | DebateOrchestrator(4 阶段: 独立并行→辩论→盲评并行→合成,单reviewer快检跳盲评),Severity 枚举排序,consensus + stability 真实计算,parse_verdict 多级降级,并行异常降级,router.py(auto 路由 + PROFILE_MAP 三档) |
| Phase 5: 置信度 + 升级路由 + AUROC 评估 | 1.5天 | EscalationRouter + Verdict/Finding Pydantic schema + run_majority_vote(保留 AaaJ 完整算法链) + evaluation.py(AUROC 校准验证) |
| Phase 6: 元审查 | 1.5天 | MetaReviewer(多 meta-reviewer 对抗) + 显式校准公式 + 递归深度控制 |
| Phase 7: 通用 CLI | 1.5天 | typer CLI + 3 种输入 + JSON 文件输出 + --interactive + --max-cost(执行中检查) + --override-model + output/ 模块 |
| Phase 8: 测试 + 文档 | 2天 | MockLLM + 10 个测试文件(含 router/evaluation/快检形态) + 4 场景集成测试 + README |
| **总计** | **~17天(3周半)** | 可用的对抗审查 CLI |

---

## 9. 风险与对策

| 风险 | 对策 | 状态 |
|---|---|---|
| litellm 对 Claude 的结构化输出支持不完整 | (B-5 已修正) `structured_output.py` 实现 tool-use 优先 + response_format 降级 + prompt 注入 + 正则解析的多级降级链 | ✅ 已对策 |
| 辩论轮次过多导致 token 成本爆炸 | `debate_rounds` 默认 2;CLI `--max-cost` 预算控制;broker `check_budget()` 超限终止 | ✅ 已对策 |
| 多 reviewer 共识度计算不科学 | (M-5 已修正) `consensus_score` = reviewer satisfied 一致比例;`stability_score` = 辩论前后立场未翻转比例 | ✅ 已对策 |
| Claude 同模型 reviewer 有共享盲区 | 鼓励 `reviewers/*.yaml` 中混用模型;`meta_reviewer_2.yaml` 强制使用 GPT-4o 异构模型 | ✅ 已对策 |
| 元审查递归成本失控 | (已修正) `--review-depth` 硬上限 2(超过报错);默认 0(不元审查) | ✅ 已对策 |
| `parse_verdict` 在非 JSON 输出时失败 | (B-5 已修正) 3 级降级: JSON 块 → 裸 JSON → `<SATISFIED>` 标签 | ✅ 已对策 |
| severity 字符串比较导致最严判定错误 | (B-1 已修正) `Severity(StrEnum)` + `.rank` 属性显式排序 | ✅ 已对策 |
| 单 reviewer 辩论自说自话 | (B-3 已修正) `len(reviewers) < 2` 时跳过辩论阶段 | ✅ 已对策 |
| 元审查 confidence 非校准 | (B-4 已修正) 显式校准公式 `calibrated = original × (1 - penalty)` | ✅ 已对策 |
| CLI review_depth 默认值矛盾 | (B-2 已修正) 默认 0;`--meta-review` 等价 `--review-depth 1` | ✅ 已对策 |
| JSON 输出到 stderr 影响管道 | (M-7 已修正) JSON 到 stdout 或文件,不到 stderr | ✅ 已对策 |
| 独立评审串行延迟高 | (M-8 已修正) Phase 1 用 `ThreadPoolExecutor` 并行 | ✅ 已对策 |
| LLM provider 改造丢失 Cost/retry | (M-3 已修正) 新 LLM 类保留 Cost 集成 + retry 机制 | ✅ 已对策 |

---

## 10. 调研依据与借鉴评估

本方案基于以下深度调研(librarian agent 报告 + DeepWiki + Context7 + 源码核对):

### 10.1 调研来源

| 来源 | 关键发现 |
|---|---|
| `metauto-ai/agent-as-a-judge` (824⭐, MIT, ICML 2025) | litellm 多模型支持;DevAsk.check() 已有 majority_vote + critical_threshold + confidence 算法;但无辩论/交叉/升级路由;绑 DevAI benchmark |
| CyberAgent 开发者博客 (2026-06-28) | agent-process-judge 是 Claude Code skill(非开源库);主动验证(judge 跑工具验证 claim);Stop-hook 自动触发;双输出(Markdown + JSON with suggested_action);3 级 verdict(✅/⚠️/❌);6 轴固定评估;欺骗检测;时间线可视化 |
| `langchain-ai/langgraph` (41k⭐) + `langgraph-supervisor-py` (1.6k⭐) | interrupt() 绑 Pregel + checkpointer;Send 原语并行 fan-out;supervisor 包已软弃用(README 推荐 tool-based supervisor);审查语义(confidence/辩论/升级路由)全需自建;无内置多 agent 辩论 |
| `okuuva/agent-review-panel` (Claude Code plugin) | 4-6 reviewer + 1-3 轮辩论 + 盲评终判 + 完整性审计;但绑 Claude Code,非独立 CLI |
| LiteLLM 官方文档 | `model="anthropic/claude-*"` + `api_key` 通用参数 → Claude 原生支持 |

### 10.2 借鉴评估表

| # | 特性 | CyberAgent | LangGraph oversight | 本方案已借鉴? | 未来可借鉴? | 纯 LLM 可实现? |
|---|---|---|---|---|---|---|
| 1 | **主动验证**(judge 跑工具验证 agent 的 claim) | ✅ 核心特性——judge 调 `gh pr checks`/读执行日志验证"测试通过"等 claim | ❌ 非 LangGraph 特性——LangGraph 暂停等人工审查,不自动验证 | ❌ 未借鉴——纯 LLM 方案无工具层 | ⚠️ 预留接口——未来可加 `verifier` 扩展点 | ❌ 需工具层 |
| 2 | **3 级 verdict**(pass / warn / fail) | ✅ ✅OK / ⚠️确认推奨 / ❌差し戻し + weakest-link 聚合 | ❌ 无 verdict 级别系统 | ⚠️ 部分——有 4 级 severity + escalate_to_human 布尔值,但未在 verdict 级别显式表达"warn" | ✅ 是——新增 `VerdictLevel` 枚举或扩展 Severity | ✅ 能 |
| 3 | **`suggested_action`**(JSON 输出含"下一步做什么") | ✅ 每轴有 suggested_action | ❌ 非 LangGraph 特性 | ❌ 未借鉴——Verdict 有 `suggestion`(改进建议)但无 `suggested_action`(下一步动作) | ✅ 是——Verdict 新增字段 + prompt 要求输出 | ✅ 能 |
| 4 | **6 轴固定评估**(上下文/操作验证/危险操作/欺骗/流程合规/安全) | ✅ 6 个固定轴 | ❌ 自定义节点 | ✅ 已实现(4.3.1)——3 个内置过程级 reviewer 模板覆盖 6 轴(4 轴完整 + 2 轴语义级),用户选择性启用 | — | ✅ 已实现 |
| 5 | **欺骗检测**(claim 与日志是否一致) | ✅ 显式评估轴 | ❌ 不内置 | ❌ 未借鉴 | ⚠️ 部分——纯 LLM 可做语义比对,但无法跑工具验证 | ⚠️ 部分 |
| 6 | **weakest-link 聚合** | ✅ 整体 verdict = 各轴最小值 | ✅ 可实现 | ⚠️ 部分——`_synthesize` 用 `Severity.rank` 最严判定,概念类似 | ❌ 已有等价机制 | ✅ 已实现 |
| 7 | **双输出**(Markdown + JSON) | ✅ 人类 Markdown(含时间线) + 机器 JSON | ❌ 非 LangGraph 特性 | ✅ 已借鉴——FR-9 双格式输出 | — | ✅ 已实现 |
| 8 | **多 agent 辩论 + 盲评终判** | ❌ 单 judge | ❌ 需自建(Send + channels) | ✅ 已借鉴——DebateOrchestrator 4 阶段(借鉴 agent-review-panel) | — | ✅ 已实现 |
| 9 | **多模型配置**(per-reviewer 指定模型) | ❌ 硬编码 sonnet | ✅ 原生 per-agent | ✅ 已借鉴——LLMBroker + ReviewerConfig.model | — | ✅ 已实现 |
| 10 | **置信度评分 + 校准** | ❌ 未指定 | ❌ 不内置 | ✅ 已借鉴——confidence + calibrated_confidence + 校准公式 | — | ✅ 已实现 |
| 11 | **`interrupt()` 暂停 + 人工介入** | ❌ Stop hook 是 fire-and-forget | ✅ 核心特性——interrupt() + checkpointer + Command(resume) | ⚠️ 概念借鉴——`--interactive` 模式低置信度时暂停等 stdin。不用 Pregel/checkpointer | ❌ 不需要——CLI 场景不需要跨会话恢复 | ✅ 已有等价 |
| 12 | **`Send` 并行 fan-out** | ❌ 单 judge | ✅ Send 原语 | ✅ 概念借鉴——用 ThreadPoolExecutor 并行 Phase 1/3 | — | ✅ 已有等价 |
| 13 | **per-task durable writes**(部分失败不丢失) | ❌ Stop hook 无状态 | ✅ 超级步内每节点输出持久化 | ❌ 未借鉴——并行异常降级是"失败 reviewer 降级为低置信度 Verdict" | ⚠️ 中价值——长流程审查时有用 | ⚠️ 需持久化层 |
| 14 | **`context: fork`**(judge 在全新上下文运行) | ✅ skill 运行在 fork 上下文 | ✅ 独立子图 | ❌ 未借鉴——但纯 LLM 每次调用本身就是独立上下文 | ❌ 不需要——纯 LLM 方案无此问题 | ✅ 天然满足 |
| 15 | **多数投票**(同模型多次调用 + 投票) | ❌ 未指定 | ❌ 不内置 | ✅ 已借鉴——保留 AaaJ 原始 `run_majority_vote` 算法 | — | ✅ 已实现 |
| 16 | **元审查 + 完整性审计** | ❌ | ❌ | ✅ 原创——2 个 meta-reviewer + 6 维度(漏判/过判/置信度失准/推理缺口/共识假象/完整性审计) | — | ✅ 已实现 |
| 17 | **Stop-hook 自动触发** | ✅ Claude Code Stop hook | ⚠️ interrupt() 是图内部触发 | ❌ 不支持(1.5 节:hook 时机不正确) | ❌ 明确不支持 | — |

### 10.3 未借鉴但高价值的点(未来扩展候选)

| # | 特性 | 来源 | 价值 | 成本 | 扩展路径 |
|---|---|---|---|---|---|
| 1 | **主动验证接口** | CyberAgent | 最高——区分"agent 说了 X"和"X 是真的",工具级强验证欺骗检测 | 中——需新增 verifier 接口 | reviewer 模板新增 `skills` 字段 + skill 适配层(1.6.4) |
| 2 | **3 级 verdict 显式化**(pass / warn / fail) | CyberAgent | 高——"⚠️ 需人工确认"中间状态避免强制 pass/fail | 低——枚举 + prompt 调整 | 扩展 Severity 或新增 VerdictLevel |
| 3 | **`suggested_action`**(下一步做什么) | CyberAgent | 中——让 verdict 可操作而非仅信息性 | 低——Verdict 新增字段 | `_build_verdict` 提取 + prompt 要求 |

> 过程级评估轴已从本表提升为正式交付(见 4.3.1 节,3 个内置过程级 reviewer 模板)。

### 10.4 与业界方案定位对比

| 方案 | 类型 | 多 agent | 辩论 | 置信度 | 工具验证 | 独立 CLI | 可扩展 | 元审查 |
|---|---|---|---|---|---|---|---|---|
| **本方案** | 纯 LLM 审查 | ✅ N reviewer | ✅ 1-3 轮 | ✅ + 校准 + 升级 | ❌ | ✅ | ✅ YAML | ✅ |
| Claude Code 内置 review | 单 agent | ❌ | ❌ | ❌ | ✅ 读文件 | ❌ skill | ❌ | ❌ |
| Codex 内置 review | 单 agent | ❌ | ❌ | ❌ | ✅ 读文件 | ❌ | ❌ | ❌ |
| 原始 AaaJ | 工具+LLM | ⚠️ 同模型多次 | ❌ | ✅ | ✅ 代码专用 | ⚠️ 绑 benchmark | ❌ 硬编码 | ❌ |
| CyberAgent | 工具+LLM | ❌ 单 judge | ❌ | ⚠️ 3 级 | ✅ 主动验证 | ❌ skill | ❌ | ❌ |
| agent-review-panel | 纯 LLM 审查 | ✅ 4-6 | ✅ 1-3 轮 | ✅ tier 分配 | ❌ | ❌ Claude Code plugin | ⚠️ 自动 persona | ❌ |
| LangGraph | 通用框架 | ✅ 自定义 | 需自建 | 需自建 | 需自建 | ✅ 纯库 | ✅ 自定义节点 | ❌ |

**本方案填补的空白**:业界唯一开源的、通用的、多 agent 辩论式的、可量化置信度的、自身可递归审查的 AI 产出审计 CLI。不替代 Claude Code / Codex 的实时 review,而是在 AI 产出链路中增加一个"质量关卡"。
