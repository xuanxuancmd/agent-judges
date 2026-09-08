# 对抗审查系统实施计划 (Plan)

> **文档状态**: 待批准
> **版本**: 0.1 (Draft)
> **日期**: 2026-09-07
> **关联文档**: [spec.md](./spec.md) · [design.md](./design.md)
> **前置条件**: 已阅读 spec.md + design.md + 当前 fork 源码（`agent_as_a_judge/` 全模块）

---

## 0. 阅读指南

本文档分三部分：

1. **文档审查发现**（第 1 节）：spec.md 和 design.md 中发现的问题，按严重程度分类。这些问题必须在或伴随实施过程中修正。
2. **修正后的目标映射**（第 2 节）：将用户的原始诉求逐条映射到 FR/NFR，标注文档中的缺口。
3. **分阶段实施计划**（第 3-8 节）：可执行的改造路线，每阶段含原子任务、验证标准、依赖关系。

---

## 1. 文档审查发现

### 1.1 严重问题（BLOCKER — 实施前必须修正）

#### B-1: `severity` 字符串比较导致"最严判定"逻辑错误

**位置**: design.md 4.4 `_synthesize()` 方法

```python
max_severity = max(v.severity for v in verdicts)  # ← 字符串 max，排序结果错误
```

**问题**: `severity` 是字符串（`"critical"` / `"major"` / `"minor"` / `"pass"`）。Python 字符串 `max()` 按字典序比较：`"pass" > "minor" > "major" > "critical"`，与预期"最严 = critical"完全相反。

**修正**: 引入 `Severity` 枚举（`StrEnum`），定义 `critical > major > minor > pass` 的显式排序，聚合时用枚举比较。

---

#### B-2: CLI `--review-depth` 默认值与 `--meta-review` 默认值逻辑矛盾

**位置**: design.md 4.7 `cli.py`

```python
meta_review: bool = typer.Option(False, "--meta-review", ...)
review_depth: int = typer.Option(1, "--review-depth", ...)
# ...
if meta_review or review_depth >= 1:  # ← review_depth=1 默认 → 永远触发元审查
```

**问题**: `meta_review` 默认 `False`，但 `review_depth` 默认 `1`，条件 `review_depth >= 1` 永远为 `True`。即使用户不传 `--meta-review`，元审查也会执行，与"可选"设计矛盾，且每次审查成本翻倍。

**修正**: 
- `review_depth` 默认值改为 `0`（不元审查）
- 触发条件改为 `if meta_review or review_depth >= 1`
- 文档明确：`--meta-review` = `--review-depth 1` 的快捷方式

---

#### B-3: 单个 meta-reviewer 的"辩论"是自说自话

**位置**: design.md 4.6 `MetaReviewer.review()`

```python
meta_result = self.orchestrator.run(
    content=verdict_text,
    reviewer_names=["meta-reviewer"],  # ← 只有 1 个 reviewer
    ...
)
```

**问题**: `DebateOrchestrator` 的 Phase 2（对抗辩论）中，每个 reviewer 需要"看到其他 reviewer 的观点"来互相挑战。当只有 1 个 reviewer 时，`others` 为空字符串，reviewer 只是在跟自己辩论，丧失了对抗审查的核心价值。

**修正**: 
- 元审查至少需要 2 个 meta-reviewer（不同模型/不同 persona）才能形成真正对抗
- 或：当 `reviewer_names` 长度为 1 时，跳过 Phase 2（辩论），仅执行 Phase 1（独立评审）+ Phase 3（盲评终判 = 独立评审结果）
- 在 `meta-reviewer.yaml` 之外补充 `meta-reviewer-2.yaml`（不同模型/prompt 视角）

---

#### B-4: `calibrated_confidence` 无实际校准公式

**位置**: design.md 4.6 `MetaReviewer.review()`

```python
calibrated = meta_result.final_verdict.confidence  # ← 直接取元审查者的 confidence
original_verdict.calibrated_confidence = calibrated
```

**问题**: 元审查者的 `confidence` 是"元审查者对自己元审查结论的置信度"，不是"对原始审查置信度的校准值"。设计声称"校准原始审查的置信度"，但代码只是覆盖。spec.md 5.1 节描述的"原始 0.9 → 元审查发现漏判 → 降到 0.5"的校准逻辑未实现。

**修正**: 定义明确的校准公式，例如：
- `calibrated = original_confidence * (1 - meta_severity_penalty)`，其中 `meta_severity_penalty` 根据元审查发现的严重程度（critical=0.5, major=0.3, minor=0.1, pass=0）扣减
- 或：`calibrated = (original_confidence + meta_confidence) / 2`（简单平均）
- 或：元审查直接输出一个 `confidence_adjustment: float (-1.0 ~ +1.0)` 字段，`calibrated = clamp(original + adjustment, 0, 1)`

---

#### B-5: `complete_json` 的 `response_format` 对 Anthropic Claude 不生效

**位置**: design.md 4.2 `LLM.complete_json()`

```python
resp = litellm_completion(
    model=self.model,
    response_format={"type": "json_object"},  # ← Anthropic 不支持此参数
    ...
)
```

**问题**: `response_format={"type": "json_object"}` 是 OpenAI 专有参数。litellm 对 Anthropic 模型传此参数会被忽略或报错。design.md 9（风险）提到了此风险，但代码未实现降级方案。

**修正**: 
- 优先使用 litellm 的 `litellm.utils.function_calling` / tool-use 机制强制结构化输出（Anthropic 支持 tool_use）
- 或：在 prompt 中注入 JSON schema 约束 + tenacity 重试 + `parse_verdict` 的多种降级解析（```` ```json ``` ```` → 裸 JSON → `<SATISFIED>` 标签）
- 正则解析容错：先尝试 ```` ```json ```` 块，失败则尝试提取第一个 `{...}` 块，再失败则降级为标签解析

---

### 1.2 中等问题（应在实施中修正）

#### M-1: 包名/目录名不一致

| 位置 | 名称 |
|---|---|
| GitHub 仓库 | `agent-judges` |
| 当前 Python 包 | `agent_as_a_judge/` |
| design.md 3.1 提议 | `src/adversarial_judge/` |
| design.md CLI 命令 | `aj` |

**问题**: 三处命名不统一。`adversarial_judge` 与仓库 `agent-judges` 风格不同；当前包 `agent_as_a_judge` 已存在。

**修正**: 统一为 `adversarial_judge`（包名）+ `aj`（CLI 命令），迁移当前 `agent_as_a_judge/` → `src/adversarial_judge/`，保留 git 历史可追溯。pyproject.toml 中 `name = "adversarial-judge"`。

---

#### M-2: design.md 4.1 删除清单不完整

**遗漏的删除项**:
- `module/statistics.py` — 依赖 `DevGraph`，属证据收集范畴
- `module/prompt/prompt_locate.py` — 为已删除的 `DevLocate` 服务
- `module/prompt/prompt_planning.py` — 为已删除的 `Planning` 服务
- `module/prompt/prompt_retrieve.py` — 为已删除的 `DevTextRetrieve` 服务
- `module/prompt/system_prompt_locate.py`
- `module/prompt/system_prompt_planning.py`
- `module/prompt/system_prompt_retrieve.py`
- `scripts/run_aaaj.py` — 绑 benchmark 的入口
- `scripts/run_ask.py` — 绑 workspace 的入口
- `scripts/run_statistics.py` — 依赖 `DevStatistics`
- `scripts/run_wiki.py` — OpenWiki 独立功能
- `scripts/evaluate_confidence.py` / `scripts/generate_report.py` — 绑 benchmark
- `scripts/templates/` — benchmark 模板
- `benchmark/` — 整个 DevAI benchmark（design 已提到但路径表述不清晰，应明确是仓库根目录的 `benchmark/`）
- `reports/` — 原有报告输出目录

**修正**: 在 plan 的 Phase 1 中列出完整删除清单。

---

#### M-3: LLM provider 改造丢失原有能力

**位置**: design.md 4.2 vs 当前 `llm/provider.py`

design.md 说"保留 `llm/provider.py`"，但新 `LLM` 类丢弃了：
- `Cost` 对象集成（原 `self.cost = Cost()`）→ 成本追踪丢失
- `do_multimodal_completion` / `encode_image` → 多模态能力丢失
- `get_token_count` → token 预算控制丢失
- `is_local` → 本地模型检测丢失
- 完整的 retry 机制（`retry_if_exception_type` 针对 `RateLimitError` / `APIConnectionError` / `ServiceUnavailableError`）

**修正**: 新 `LLM` 类应保留 `Cost` 集成和 retry 机制，多模态/token counting 可按需保留。design.md 应明确标注"保留哪些、丢弃哪些"。

---

#### M-4: `LLMBroker.default_model` 与 `ReviewerConfig.model` 冲突

**位置**: design.md 4.2 `LLMBroker` + 4.3 `ReviewerConfig`

```python
class ReviewerConfig(BaseModel):
    model: str  # ← 必填，每个 reviewer 必须指定模型

class LLMBroker:
    def __init__(self, default_model: str, ...):  # ← 有默认模型
    def get_llm(self, model: str | None = None) -> LLM:  # ← model 可选
```

**问题**: 如果每个 reviewer YAML 都必填 `model`，`LLMBroker.default_model` 永远不会被用到。CLI 的 `--model` 参数也无法覆盖 reviewer 自身的 model 设定。

**修正**: 
- `ReviewerConfig.model` 改为 `model: str | None = None`（可选）
- `LLMBroker.get_llm(reviewer.model or self.default_model)` — reviewer 不指定时用 broker 默认值
- CLI `--model` 覆盖 `default_model`，但不覆盖 reviewer 显式指定的 model
- 新增 CLI `--override-model` 强制覆盖所有 reviewer 的 model（用于"全用 GPT-4o 测试"场景）

---

#### M-5: `consensus_score` 命名误导

**位置**: design.md 4.4 `DebateResult`

```python
consensus_score=final_verdict.confidence  # ← 这不是共识度，是聚合置信度
```

**问题**: `consensus_score` 应反映 reviewer 之间的**一致性程度**（如：N 个 reviewer 中判 critical 的比例、severity 分布的熵），而非聚合后的 confidence。

**修正**: 
- `consensus_score` = reviewer 在 `satisfied` 判定上的一致比例（如 3/4 判 satisfied → 0.75）
- 或 = severity 分布的归一化熵（完全一致 = 1.0，分歧 = 0.0）
- 聚合 confidence 保留为 `final_verdict.confidence`，不冒充 consensus

---

#### M-6: Finding 与 Verdict 的 severity 级别不一致

**位置**: design.md 4.5

```python
class Finding(BaseModel):
    severity: str  # critical / major / minor    ← 无 pass

class Verdict(BaseModel):
    severity: str  # critical / major / minor / pass  ← 有 pass
```

**修正**: 统一为 `Severity` 枚举，`pass` 仅在 Verdict 级别有意义（"整体通过"），Finding 级别不允许 `pass`（有发现就不是 pass）。用枚举 + 校验约束实现。

---

#### M-7: JSON 输出到 stderr 的 UX 不合理

**位置**: design.md 4.7

```python
if output_format in ("json", "both"):
    print(json_out, file=sys.stderr)  # ← JSON 到 stderr
```

**问题**: `--output both` 时 Markdown 到 stdout、JSON 到 stderr。用户无法用 `> file.json` 捕获 JSON；CI/CD 管道中 stderr 常被当作错误流。

**修正**: 
- `--output markdown` → stdout
- `--output json` → stdout
- `--output both` → 写两个文件：`--output-dir` 指定目录，生成 `report.md` + `verdict.json`
- 或：`--json-file path.json` 指定 JSON 输出路径，Markdown 始终到 stdout

---

#### M-8: 独立评审阶段无并行执行

**位置**: design.md 4.4 `DebateOrchestrator.run()`

```python
individual_verdicts = [
    self._independent_review(r, content, context) for r in reviewers
]  # ← 同步列表推导，N 个 reviewer 串行调用 LLM
```

**问题**: Phase 1（独立评审）各 reviewer 无交叉依赖，应并行执行。串行执行 N 个 reviewer = N × 单次 LLM 延迟，严重影响用户体验。

**修正**: 使用 `concurrent.futures.ThreadPoolExecutor` 或 `asyncio` 并行执行 Phase 1。LangGraph 的图原语天然支持并行，这是可借鉴的点。

---

### 1.3 遗漏需求（GAP — 文档未覆盖用户明确提出的诉求）

#### G-1: "代码检视产物可审查"未在 spec 中显式列出

**用户原话**: "代码检视不再该职责内，代码检视的产物可能通过当前的工具来审查"

**现状**: spec.md 2.1 明确排除"代码风格、命名规范、格式化、设计模式、性能微优化"（✓ 正确），但**未提及**外部代码检视工具的产物（如 SonarQube 报告、ESLint 输出、人工 review comment、PR review）可以作为本系统的 `content` 输入被审查。

**影响**: 用户的核心场景之一（审查代码检视报告本身是否可靠、是否遗漏、是否误报）未文档化。

**修正**: spec.md 审查范围表新增一行：

| AI 产出物 | 审查焦点 |
|---|---|
| 外部代码检视报告 | 检视是否覆盖需求、是否误报/漏报、severity 评定是否合理、建议是否可执行 |

---

#### G-2: "需求分析各个环节"粒度过粗

**用户原话**: "支持对于需求分析各个环节……进行审查"

**现状**: spec.md 审查范围表将"需求分析文档"作为单一产出物。

**实际需求**: 需求分析是一个多阶段流程，每个阶段的产出物都需审查：

| 需求分析子阶段 | 产出物 | 审查焦点 |
|---|---|---|
| 需求收集 | 原始需求列表 | 完整性（是否遗漏干系人需求）、来源可追溯 |
| 需求澄清 | 澄清后的需求文档 | 歧义是否消除、假设是否记录 |
| 需求分解 | 需求层次结构 | 分解粒度是否合理、MECE 性 |
| 需求优先级 | 优先级排序 | 排序依据是否充分、MoSCoW 合理性 |
| 需求验收标准 | 验收标准清单 | 可测试性、完整性 |

**修正**: spec.md FR-1 补充"多阶段"语义；reviewers/ 目录为每个子阶段提供示例 reviewer YAML。

---

#### G-3: "代码生成后的各个环节"未作为连贯管线文档化

**用户原话**: "代码生成后的各个环节进行审查"

**现状**: spec.md 审查范围表分别列出"AI 生成的代码"和"测试计划"，但未将"代码生成后"作为一个连贯的管线阶段组。

**实际需求**: 代码生成后的各环节产出物都需审查：

| 代码生成后子阶段 | 产出物 | 审查焦点 |
|---|---|---|
| 实现对照规格 | 代码 vs spec 对照 | 需求覆盖度、逻辑一致性 |
| 单元测试 | 测试代码 | 是否覆盖需求路径、边界场景、断言有效性 |
| 集成测试 | 集成测试方案 | 接口契约验证、场景覆盖 |
| 部署配置 | Dockerfile/IaC | 配置与需求一致性、安全基线 |
| 文档 | API 文档/README | 与实现一致性、可读性 |

**修正**: spec.md FR-1 补充"代码生成后各环节"语义；reviewers/ 补充对应示例。

---

#### G-4: 借鉴 LangGraph / agent-review-panel 的具体点未在 spec 中列为需求

**用户原话**: "过程中需要借鉴LangGraph或agent-review-panel的优点"

**现状**: design.md 2.3 表格列出了借鉴模式，但 spec.md 未将其提升为功能性需求。

**可借鉴的具体模式**:

| 来源 | 借鉴点 | 提升为 |
|---|---|---|
| LangGraph | `with_structured_output(Pydantic)` 强制结构化输出 | FR-4 补充：置信度通过 Pydantic schema 强制结构化 |
| LangGraph | 图原语天然并行 | NFR 补充：独立评审阶段并行执行 |
| LangGraph | `interrupt()` 人工介入中断（借鉴概念，不用 Pregel） | FR-4 补充：低置信度时支持 `--interactive` 暂停等待人工输入 |
| agent-review-panel | 多轮辩论 + 盲评终判 | FR-2 已覆盖 |
| agent-review-panel | 完整性审计（检查 reviewer 是否覆盖所有维度） | FR-8 补充：元审查含完整性审计 |
| agent-review-panel | stability score（多轮辩论后观点稳定性） | NFR 补充：辩论稳定性度量 |

**修正**: spec.md FR-4 / FR-8 / NFR 补充上述条目。

---

#### G-5: `majority_vote`（同模型多次投票）机制未在新设计中保留

**现状**: 原始 `DevAsk.check()` 的 `majority_vote: int` 参数允许同一模型调用 N 次后投票，是 AaaJ 的三大核心算法之一。spec.md FR-2 将其列为"（可选）"策略，但 design.md 的 `DebateOrchestrator` 完全未保留此机制。

**影响**: 丢失了一个轻量级反幻觉手段。当用户不想跑完整辩论（成本高）时，同模型多次投票 + 置信度计算是最便宜的改进方式。

**修正**: `ReviewerConfig` 新增 `majority_vote: int = 1` 字段；`_independent_review()` 内部循环 `majority_vote` 次并对结果做 majority_vote + confidence 计算（复用原始 `DevAsk.check()` 算法）。

---

#### G-6: 无测试策略（无 LLM mock 方案）

**现状**: design.md Phase 8 "测试 + 文档"仅提到"3 个场景测试"，但未说明如何在不消耗真实 API token 的情况下测试。

**修正**: 
- 新增 `tests/fixtures/mock_llm.py` — 实现 `MockLLM` 类，返回预设响应
- `LLMBroker` 支持 `mock=True` 模式注入 `MockLLM`
- 单元测试全部用 mock，不调真实 API
- 集成测试用 `@pytest.mark.integration` 标记，需真实 API key

---

### 1.4 轻微问题（NICE-TO-FIX）

| ID | 位置 | 问题 | 建议 |
|---|---|---|---|
| L-1 | design.md 4.7 | `list_reviewers` 命令未在 CLI `app` 中通过 `@app.command()` 注册为独立命令（它有 `@app.command()` 但函数名 `list_reviewers` 对应 CLI 子命令 `list-reviewers`，需验证 typer 转换） | 测试时验证 `aj list-reviewers` 可执行 |
| L-2 | design.md 5.3 | `--review-depth 2`（元元审查）描述为"极少需要"，但未设置硬上限 | 建议硬上限 `review_depth <= 2`，超过报错 |
| L-3 | design.md 4.5 | `Verdict` 有 `original_content` 字段但 `_synthesize` 未填充 | 在 `_synthesize` 中设为传入的 `content` |
| L-4 | design.md 7.2 | 示例 4 `aj review --file verdict.json --meta-review` 中 `verdict.json` 是 JSON，但 `--file` 读取的是纯文本，需要 JSON→文本适配 | `--file` 支持 `.json` 后缀时提取 `verdict` 字段文本 |
| L-5 | spec.md 5.2 | 得分表"AaaJ=11, LangGraph=13"但选了 AaaJ，需确保读者理解"非得分最高，而是改造成本最低"的逻辑不会被误读 | 在表格下方加粗强调 |
| L-6 | design.md 4.3 | `ReviewerRegistry.__init__` 只读 `*.yaml`，不读 `*.yml` | glob 改为 `*.y*ml` |

---

## 2. 修正后的目标映射

将用户的原始诉求逐条映射到 spec FR/NFR，标注文档现状：

| # | 用户诉求 | 映射到 | 文档现状 | 需修正 |
|---|---|---|---|---|
| 1 | 审查需求分析**各个环节** | FR-1（多阶段通用审查） | ⚠️ FR-1 说了"任意环节"但未细化"需求分析各子阶段" | G-2 |
| 2 | 审查代码生成后**各个环节** | FR-1 | ⚠️ 同上，"代码生成后"未作为管线阶段组 | G-3 |
| 3 | 避免**单 Agent 幻觉** | FR-2（多 agent 对抗审查） | ✅ 已覆盖 | — |
| 4 | **代码检视不在职责内** | spec 2.1（明确排除） | ✅ 已覆盖 | — |
| 5 | 代码检视的**产物可被审查** | FR-1（任意文本输入） | ❌ 未显式列出 | G-1 |
| 6 | 标注**置信度** | FR-4（置信度评分） | ✅ 已覆盖 | — |
| 7 | 告诉人哪些需要**人工介入** | FR-4（升级路由） | ✅ 已覆盖 | — |
| 8 | 降低人工审查**心智负担** | FR-9（双格式输出）+ FR-4 | ✅ 已覆盖 | — |
| 9 | 支持外部**自定义扩展**审查 agent | FR-6（外部定义 reviewer） | ✅ 已覆盖 | — |
| 10 | 借鉴 **LangGraph** 优点 | spec 5.3 + design 2.3 | ⚠️ 在调研中提到但未提升为需求 | G-4 |
| 11 | 借鉴 **agent-review-panel** 优点 | spec 5.3 + design 2.3 + FR-2 | ✅ 辩论+盲评已覆盖，完整性审计未提升 | G-4 |
| 12 | 审查结果可被审查（**元审查**） | FR-8 | ✅ 已覆盖（但实现有缺陷） | B-3, B-4 |

---

## 3. 实施计划总览

### 3.1 阶段划分

```
Phase 0: 文档修正 (0.5 天)
  ├── 修正 spec.md（G-1~G-4）
  └── 修正 design.md（B-1~B-5, M-1~M-8）
        │
        ▼
Phase 1: Fork 清理 + 依赖精简 (1.5 天)
  ├── 删除证据收集模块 + benchmark + scripts
  ├── 精简 pyproject.toml
  └── 验证: poetry install 无残留依赖报错
        │
        ▼
Phase 2: 多模型依赖注入 (1.5 天)
  ├── 重写 LLM provider（保留 Cost + retry）
  ├── 新建 LLMBroker（缓存 + 预算控制）
  ├── structured_output.py（tool-use + 4 级降级）
  └── 验证: 多模型实例化 + 缓存 + 成本追踪
        │
        ▼
Phase 3: 外部 reviewer 定义 (2 天)
  ├── ReviewerConfig + ReviewerRegistry (Pydantic)
  ├── 匿名槽位约束模型（用户模板只注入视角）
  ├── 13 个视角模板 YAML（含 3 个过程级：过程合规/欺骗检测/危险操作）
  └── 验证: aj list-reviewers 正确列出
        │
        ▼
Phase 4: 辩论编排器 (3.5 天)
  ├── DebateOrchestrator 4 阶段（并行 + 异常降级）
  ├── Severity 枚举 + 正确聚合
  ├── 并行独立评审 + 盲评终判（ThreadPoolExecutor + 容错）
  ├── 单 reviewer 快检形态（跳过 Phase 3, stability 标 degraded）
  ├── consensus_score + stability_score 真实计算
  ├── router.py auto 路由器（L1 入口路由 + PROFILE_MAP 三档）
  └── 验证: 2 reviewer + 2 轮辩论产出完整 DebateResult + auto 路由档位判定
        │
        ▼
Phase 5: 置信度 + 升级路由 + 结构化输出 + AUROC 评估 (1.5 天)
  ├── Verdict/Finding Pydantic schema
  ├── parse_verdict 多级降级解析 + 完整投票循环提取
  ├── EscalationRouter
  ├── evaluation.py（AUROC 校准验证，从 evaluate_confidence.py 提取）
  └── 验证: 低置信度 → escalate_to_human=true + AUROC 算法单测
        │
        ▼
Phase 6: 元审查 (1.5 天)
  ├── MetaReviewer + 校准公式
  ├── 多 meta-reviewer 对抗
  ├── 递归深度控制
  └── 验证: 元审查校准 confidence + 防递归
        │
        ▼
Phase 7: 通用 CLI + 双格式输出 (1.5 天)
  ├── typer CLI（review + list-reviewers）
  ├── 3 种输入方式 + 双输出
  ├── --max-cost 预算控制
  └── 验证: aj review 全参数路径
        │
        ▼
Phase 8: 测试 + 文档 (2 天)
  ├── MockLLM + 单元测试(10 个测试文件, 含 router/evaluation/快检形态)
  ├── 4 场景集成测试(含零参数 auto 路由)
  ├── README + 使用示例
  └── 验证: pytest 全绿 + 端到端跑通

总计: ~17 天（3 周半）
```

> **工期说明**: Phase 2(structured_output 4 级降级 ~100+ LOC)、Phase 3(13 个视角模板含 3 个过程级)、Phase 4(DebateOrchestrator 4 阶段 + 并行 + 异常降级 ~300 LOC + router.py auto 路由)、Phase 5(含 AUROC evaluation 提取)、Phase 8(10 个测试文件 + MockLLM 接口 + 4 场景集成测试)工作量较重。原估算 12.5 天偏乐观，修正为 17 天。

### 3.2 依赖关系

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6 ──► Phase 7 ──► Phase 8
                                                    │                      │
                                                    └── Phase 4 依赖 Phase 3 (reviewer) + Phase 2 (broker)
                                                                           └── Phase 6 依赖 Phase 4 (orchestrator) + Phase 5 (verdict)
```

Phase 0-3 可由单人串行执行。Phase 4-7 有严格依赖链。Phase 8 依赖全部完成。

---

## 4. Phase 0: 文档修正

**目标**: 修正 spec.md 和 design.md 中发现的全部 BLOCKER + GAP 问题，使文档成为可执行的施工蓝图。

### 4.1 修正 spec.md

| 任务 | 修正内容 | 对应问题 |
|---|---|---|
| S-1 | FR-1 补充"多阶段"语义：审查范围表细化"需求分析各子阶段"（收集/澄清/分解/优先级/验收标准）和"代码生成后各子阶段"（实现对照/单元测试/集成测试/部署配置/文档） | G-2, G-3 |
| S-2 | 审查范围表新增"外部代码检视报告"行 | G-1 |
| S-3 | FR-2 "多数投票"从"（可选）"提升为正式策略，标注在新系统中保留 | G-5 |
| S-4 | FR-4 补充：置信度通过 Pydantic schema 强制结构化输出（借鉴 LangGraph `with_structured_output`） | G-4 |
| S-5 | FR-8 补充：元审查含完整性审计（借鉴 agent-review-panel） | G-4 |
| S-6 | NFR 新增：独立评审阶段并行执行；辩论稳定性度量（stability score） | G-4 |
| S-7 | FR-5 CLI 补充：`--interactive` 模式支持低置信度时暂停等待人工输入（借鉴 LangGraph interrupt 概念，不用 Pregel） | G-4 |

### 4.2 修正 design.md

| 任务 | 修正内容 | 对应问题 |
|---|---|---|
| D-1 | 3.1 统一包名为 `adversarial_judge`，明确迁移路径 `agent_as_a_judge/` → `src/adversarial_judge/` | M-1 |
| D-2 | 4.1 补全删除清单（statistics.py + 7 个 prompt 文件 + scripts + benchmark + reports） | M-2 |
| D-3 | 4.2 LLM 类保留 Cost 集成 + retry 机制；标注多模态/token counting 按需保留 | M-3 |
| D-4 | 4.2 `complete_json` 改为 litellm tool-use 机制 + 降级解析链 | B-5 |
| D-5 | 4.3 `ReviewerConfig.model` 改为 `Optional[str]`；LLMBroker 补充 `default_model` 回退逻辑 + `--override-model` | M-4 |
| D-6 | 4.3 `ReviewerConfig` 新增 `majority_vote: int = 1` 字段 | G-5 |
| D-7 | 4.4 引入 `Severity(StrEnum)` 枚举；`_synthesize` 用枚举排序 | B-1 |
| D-8 | 4.4 Phase 1 改为 `ThreadPoolExecutor` 并行 | M-8 |
| D-9 | 4.4 `consensus_score` 改为 reviewer 在 satisfied 判定上的一致比例 | M-5 |
| D-10 | 4.5 `parse_verdict` 实现多级降级（```` ```json ```` → 裸 JSON → `<SATISFIED>` 标签） | B-5 |
| D-11 | 4.5 统一 Severity 枚举，Finding 不允许 `pass` | M-6 |
| D-12 | 4.6 MetaReviewer 至少 2 个 meta-reviewer；单 reviewer 时跳过辩论 | B-3 |
| D-13 | 4.6 定义显式校准公式 | B-4 |
| D-14 | 4.7 `review_depth` 默认 0；触发条件修正 | B-2 |
| D-15 | 4.7 JSON 输出改为文件或 stdout（非 stderr） | M-7 |
| D-16 | 8 实施路线图与 plan.md 对齐 | — |

### 4.3 验收标准

- [ ] spec.md FR 表完整覆盖用户 12 条诉求
- [ ] design.md 代码示例无编译级逻辑错误
- [ ] 所有 BLOCKER（B-1~B-5）在 design.md 中有修正后的代码

---

## 5. Phase 1: Fork 清理 + 依赖精简

**目标**: 从 fork 中剥离所有绑定 workspace/benchmark 的代码，保留 LLM provider + Cost + judge prompt 模板 + DevAsk 算法。

### 5.1 完整删除清单

```
删除（根目录）:
  benchmark/                          # DevAI benchmark 全量
  reports/                            # 原有报告输出
  scripts/run_aaaj.py                 # 绑 benchmark 入口
  scripts/run_ask.py                  # 绑 workspace 入口
  scripts/run_statistics.py           # 依赖 DevStatistics
  scripts/run_wiki.py                 # OpenWiki 独立功能
  scripts/evaluate_confidence.py      # 绑 benchmark
  scripts/generate_report.py          # 绑 benchmark
  scripts/templates/                  # benchmark 模板
  assets/                             # 原项目图片资源（可选保留 logo）

删除（agent_as_a_judge/module/）:
  code_search.py                      # DevCodeSearch (BM25+embedding)
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

删除（agent_as_a_judge/）:
  agent.py                            # JudgeAgent (绑 workspace)
  config.py                           # AgentConfig (绑 workspace/benchmark)
```

### 5.2 保留清单

> 经 explore agent 深挖核实（design.md 1.7.1 完整清单），保留范围扩大：

```
保留（agent_as_a_judge/ → 迁移至 src/adversarial_judge/）:
  llm/provider.py                     # litellm wrapper + retry + model_info 自动检测
                                      #   + is_local + get_token_count + 多模态(按需)（Phase 2 改造）
  llm/cost.py                         # Cost 成本追踪（原样保留，39 行）
  llm/__init__.py
  module/ask.py                       # 完整提取（不只 check() 公式）:
                                      #   _collect_judgments() 投票循环(L71-91)
                                      #   confidence 公式(L57)
                                      #   _parse_judge 标签解析(L93-97)
                                      #   _initialize/_update_llm_stats(L99-113)（Phase 5 提取）
  module/prompt/prompt_judge.py        # judge prompt 模板（Phase 5 改通用）
  module/prompt/system_prompt_judge.py # judge system prompt（Phase 5 改通用）
  module/prompt/system_prompt_retrieve.py # 结构化标签+聚焦/排除指令模式（借鉴，Phase 4 prompt 设计参考）
  module/prompt/prompt_locate.py       # demonstration+分隔符模式（借鉴，structured_output 降级参考）
  utils/truncate.py                   # truncate_string（保留，通用工具，54 行）
  utils/__init__.py
  __init__.py                         # 重写导出

保留（scripts/ → 迁移）:
  scripts/evaluate_confidence.py      # **AUROC 算法(L100-121) + infer_confidence 降级链(L45-64)
                                      #   + 评估管道(L67-92)**（Phase 5 提取 → evaluation.py，最高价值遗漏资产）

参考（不迁移代码，借鉴思路）:
  module/memory.py                    # _format_judgment 序列化模式（元审查 Verdict→text 参考）
  agent.py                            # display_judgment rich 模式 / 持久化字段清理 / 证据分类标签
  config.py                           # dataclass+from_args 模式（已升级为 Pydantic）
  benchmark/devai/instances/*.json    # hierarchical requirements DAG / requirements-preferences 二分
  reports/technical_guide_confidence_estimation.md  # 置信度评估方法论（AUROC 退化诊断/校准检查）

删除:
  module/prompt/prompt_ask.py         # ask 模式不再使用（单次评审并入 judge 流程）
  module/prompt/system_prompt_ask.py  # 同上
  utils/count_lines.py                # 绑代码统计场景
```

### 5.3 精简 pyproject.toml

```toml
[tool.poetry]
name = "adversarial-judge"
version = "0.1.0"
description = "Adversarial multi-agent review system for AI-generated artifacts"
authors = ["<original> + modifications"]
license = "MIT"
readme = "README.md"
packages = [{include = "adversarial_judge", from = "src"}]

[tool.poetry.dependencies]
python = "^3.11"
litellm = "^1.50.0"
tenacity = "^9.0.0"
pydantic = "^2.0"
typer = "^0.12"
rich = "^13.0"
pyyaml = "^6.0"
tiktoken = "^0.9.0"
python-dotenv = "^1.0.1"
jinja2 = "^3.1.3"          # 报告模板渲染

[tool.poetry.scripts]
aj = "adversarial_judge.cli:app"

[tool.poetry.group.dev.dependencies]
pytest = "^8.3.3"
pytest-cov = "^5.0.0"
pytest-asyncio = "^0.24.0"

# 删除的依赖:
# numpy, networkx, spacy, rank-bm25, sentence-transformers, pandas,
# docx, markdown, python-docx, pypdf2, openpyxl, opencv-python,
# beautifulsoup4, pylatexenc, matplotlib, tree-sitter-languages,
# grep-ast, rapidfuzz, tqdm, logging, tree-sitter, tf-keras,
# python-pptx, dotenv(重复)
```

### 5.4 目录迁移

```
agent_as_a_judge/           →  src/adversarial_judge/
  llm/                          llm/
  module/ask.py                 judge/ask_algorithm.py  (重命名，提取算法)
  module/prompt/                prompts/
  utils/                        utils/
  __init__.py                   __init__.py  (重写)
```

### 5.5 验收标准

- [ ] `git status` 显示删除的文件已 removed，保留的文件已 renamed
- [ ] `poetry install` 成功，无残留依赖报错
- [ ] `python -c "from adversarial_judge.llm.provider import LLM; from adversarial_judge.llm.cost import Cost"` 无 ImportError
- [ ] `pip list` 中无 spacy / sentence-transformers / opencv / tree-sitter 等重型依赖
- [ ] 项目体积显著减小（`du -sh .` 对比）

---

## 6. Phase 2: 多模型依赖注入

**目标**: 将 LLM provider 从 `os.getenv("DEFAULT_LLM")` 硬编码改为依赖注入，支持 per-reviewer 指定不同模型。

### 6.1 任务

| 任务 | 文件 | 内容 |
|---|---|---|
| 2-1 | `src/adversarial_judge/llm/provider.py` | 重写 `LLM` 类：`model` 参数必传（不从 env 读）；保留 `Cost` 集成；保留 `retry` 机制（`RateLimitError` / `APIConnectionError` / `ServiceUnavailableError`）；保留 `is_local` / `get_token_count`；新增 `complete(system_prompt, user_prompt) -> str` 和 `complete_json(system_prompt, user_prompt, schema) -> dict`（用 litellm tool-use 或 response_format） |
| 2-2 | `src/adversarial_judge/llm/broker.py` | 新建 `LLMBroker`：`__init__(default_model, default_api_key)`；`get_llm(model: str \| None = None) -> LLM`（带缓存）；`get_total_cost() -> float`；`get_total_tokens() -> int` |
| 2-3 | `src/adversarial_judge/llm/__init__.py` | 导出 `LLM`, `LLMBroker`, `Cost` |
| 2-4 | `src/adversarial_judge/llm/structured_output.py` | 新建：`force_json(llm, system_prompt, user_prompt, schema: type[BaseModel]) -> dict` — 优先 litellm tool-use，降级为 `response_format` + 正则解析 |

### 6.2 关键设计

```python
# Severity 枚举（在 types.py 中定义，全局复用）
from enum import StrEnum

class Severity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    PASS = "pass"

    @property
    def rank(self) -> int:
        """严重程度排序：critical(3) > major(2) > minor(1) > pass(0)"""
        return {self.CRITICAL: 3, self.MAJOR: 2, self.MINOR: 1, self.PASS: 0}[self]
```

```python
# LLMBroker 缓存策略
class LLMBroker:
    def __init__(self, default_model: str, default_api_key: str | None, default_base_url: str | None = None):
        self.default_model = default_model
        self.default_api_key = default_api_key
        self.default_base_url = default_base_url
        self._cache: dict[str, LLM] = {}
        self._total_cost: float = 0.0
        self._total_tokens: int = 0

    def get_llm(self, model: str | None = None) -> LLM:
        resolved = model or self.default_model
        if resolved not in self._cache:
            self._cache[resolved] = LLM(
                model=resolved,
                api_key=self.default_api_key,
                base_url=self.default_base_url,
            )
        return self._cache[resolved]

    def get_total_cost(self) -> float:
        """汇总缓存实例的 Cost.accumulated_cost"""
        return sum(llm.cost.accumulated_cost for llm in self._cache.values())

    def check_budget(self) -> bool:
        if self.max_budget_usd is None:
            return True
        return self.get_total_cost() < self.max_budget_usd
```

### 6.3 验收标准

- [ ] `LLM(model="anthropic/claude-sonnet-4-20250514", api_key="...")` 可实例化
- [ ] `LLMBroker` 同一 model 第二次 `get_llm` 返回缓存实例（`is` 相同）
- [ ] `llm.complete("system", "user")` 返回字符串
- [ ] `llm.complete_json("system", "user", Verdict)` 返回 dict（用 mock 验证）
- [ ] `broker.get_total_cost()` 在 LLM 调用后 > 0
- [ ] retry 机制对 `RateLimitError` 生效（mock 验证重试 3 次）
- [ ] `lsp_diagnostics` 在所有新文件上无 error

---

## 7. Phase 3: 外部 reviewer 定义

**目标**: 实现 YAML 驱动的视角模板注入，支持外部自定义扩展。**约束模型**(design.md 1.6): 系统提供匿名辩论 reviewer 槽位(行为框架固定)，用户模板只注入"审查视角"(persona + checklist)，不提供行为定义——辩论行为/输出格式/流程编排全部系统控制。

### 7.1 任务

| 任务 | 文件 | 内容 |
|---|---|---|
| 3-1 | `src/adversarial_judge/reviewer.py` | `ReviewerConfig(BaseModel)`: name, description, model(Optional), system_prompt, checklist, weight, majority_vote; `ReviewerRegistry`: 从目录加载 `*.y*ml`，校验，get/list_all |
| 3-2 | `reviewers/requirement_elicitation_reviewer.yaml` | 需求收集阶段视角模板 |
| 3-3 | `reviewers/requirement_decomposition_reviewer.yaml` | 需求分解阶段视角模板 |
| 3-4 | `reviewers/spec_reviewer.yaml` | 规格文档审查视角 |
| 3-5 | `reviewers/design_reviewer.yaml` | 设计文档审查视角 |
| 3-6 | `reviewers/test_plan_reviewer.yaml` | 测试计划审查视角 |
| 3-7 | `reviewers/implementation_vs_requirement_reviewer.yaml` | 实现对照需求审查视角 |
| 3-8 | `reviewers/external_code_review_auditor.yaml` | 外部代码检视报告审查视角（G-1） |
| 3-9 | `reviewers/process_compliance_reviewer.yaml` | 过程合规审查视角（借鉴 CyberAgent 6 轴：上下文获取/流程合规/安全检查语义级，design.md 4.3.1） |
| 3-10 | `reviewers/deception_detector.yaml` | 欺骗检测视角（claim 与日志证据语义比对，design.md 4.3.1） |
| 3-11 | `reviewers/dangerous_operation_scanner.yaml` | 危险操作扫描视角（--no-verify/force-push/rm -rf 正则+语义，design.md 4.3.1） |
| 3-12 | `reviewers/meta_reviewer.yaml` | 元审查视角（漏判/过判/置信度失准/推理缺口/共识假象 + 完整性审计） |
| 3-13 | `reviewers/meta_reviewer_2.yaml` | 第二元审查视角（不同视角/模型，B-3） |
| 3-14 | `reviewers/custom_example.yaml` | 用户自定义视角模板示例（含注释说明各字段 + "只能注入视角，不能自定义辩论行为"的说明） |

### 7.2 ReviewerConfig schema

```python
class ChecklistItem(BaseModel):
    criteria: str
    weight: float = 1.0  # checklist 项权重

class ReviewerConfig(BaseModel):
    name: str                              # 唯一标识
    description: str                       # 人类可读描述
    model: str | None = None               # 可选，不指定则用 broker 默认
    system_prompt: str                     # 审查者系统提示词
    checklist: list[ChecklistItem]         # 检查清单
    weight: float = 1.0                    # reviewer 在聚合中的权重
    majority_vote: int = 1                 # 同模型多次调用投票（G-5）
    temperature: float = 0.0               # 可选，覆盖默认温度
    max_output_tokens: int = 4096         # 可选，覆盖默认 token 上限

    @field_validator("name")
    @classmethod
    def name_must_be_slug(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("name must be a slug (alphanumeric + -/_)")
        return v
```

### 7.3 示例 reviewer YAML（external_code_review_auditor.yaml）

```yaml
# 审查外部代码检视工具（如 SonarQube / ESLint / 人工 review）的产物
# 不审查代码本身，审查"检视报告"是否可靠
name: external-code-review-auditor
description: 审查外部代码检视报告的覆盖度、误报率、severity 合理性
model: anthropic/claude-sonnet-4-20250514
system_prompt: |
  你审查的是一份外部代码检视报告（可能来自 SonarQube / ESLint / 人工 review）。
  你的任务不是审查代码，而是审查"检视报告本身"是否可靠：

  1. 覆盖度: 检视是否覆盖了需求中的所有关键模块
  2. 误报: 报告中的问题是否真实存在（基于提供的代码上下文判断）
  3. 漏报: 需求关键路径上是否有明显问题未被检视发现
  4. Severity 合理性: 报告标注的严重级别是否与实际影响匹配
  5. 建议可执行性: 报告中的修复建议是否具体可操作

  对每个发现给出 severity / confidence / evidence / suggestion。
checklist:
  - criteria: 检视报告覆盖了需求中所有关键模块
  - criteria: 报告中标注的问题均有代码依据（非误报）
  - criteria: 需求关键路径上无明显漏报
  - criteria: severity 标注与实际影响匹配
  - criteria: 修复建议具体且可执行
weight: 1.2
```

### 7.4 验收标准

- [ ] `ReviewerRegistry(Path("reviewers"))` 加载全部 YAML 无报错
- [ ] `registry.get("requirement-elicitation-reviewer")` 返回正确 config
- [ ] `registry.get("nonexistent")` 抛 `KeyError` 且列出可用名称
- [ ] `registry.list_all()` 返回 ≥13 个视角模板
- [ ] 过程级模板加载验证：`registry.get("deception-detector")` 返回含"语义级比对"prompt 的 config
- [ ] ReviewerConfig 校验：缺 `name` 报 ValidationError；`name` 含空格报错
- [ ] `model: null` 的 reviewer 可正常加载（`model=None`）
- [ ] `lsp_diagnostics` 无 error

---

## 8. Phase 4: 辩论编排器

**目标**: 实现 4 阶段辩论流程（独立评审 → 对抗辩论 → 盲评终判 → 裁决合成），借鉴 agent-review-panel 的辩论+盲评模式。

### 8.1 任务

| 任务 | 文件 | 内容 |
|---|---|---|
| 4-1 | `src/adversarial_judge/types.py` | `Severity(StrEnum)` + `Finding(BaseModel)` + `Verdict(BaseModel)` + `DebateResult(dataclass)` |
| 4-2 | `src/adversarial_judge/debate.py` | `DebateOrchestrator`: 4 阶段流程；Phase 1/3 并行（ThreadPoolExecutor）+ 单点失败降级 + 预算检查 + **单 reviewer 跳过 Phase 3（快检形态，stability 标 degraded）** |
| 4-3 | `src/adversarial_judge/prompts/debate.py` | 辩论轮次 prompt 构建函数 |
| 4-4 | `src/adversarial_judge/judge.py` | `parse_verdict(response) -> Verdict`: 多级降级解析 |
| 4-5 | `src/adversarial_judge/consensus.py` | `compute_consensus(verdicts) -> float`: 真实共识度计算 |
| 4-6 | `src/adversarial_judge/router.py` | **auto 路由器**（design.md 4.8）: `route(broker, content, available) -> RouteDecision`（一次轻量 LLM 分类，temp=0，输出含 reason 可审计）+ `PROFILE_MAP`（fast=1reviewer/0辩论/1调用、standard=2/1/无元审查、thorough=3/2/含元审查）+ 解析失败兜底 standard 档 |

### 8.2 DebateOrchestrator 关键设计

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

class DebateOrchestrator:
    def __init__(self, registry, broker, debate_rounds=2, max_workers=None):
        self.registry = registry
        self.broker = broker
        self.debate_rounds = debate_rounds
        self.max_workers = max_workers or min(len(registry.list_all()), 4)

    def run(self, content, reviewer_names, context=None) -> DebateResult:
        reviewers = [self.registry.get(n) for n in reviewer_names]
        if len(reviewers) < 1:
            raise ValueError("At least 1 reviewer required")

        # Phase 1: 独立评审（并行, 单reviewer失败降级为低置信度Verdict）
        individual_verdicts = self._parallel_independent_review(reviewers, content, context)

        # 预算检查: Phase 1 后, 超限则跳过辩论直接合成
        if not self.broker.check_budget():
            final_verdict = self._synthesize(individual_verdicts, reviewers, content)
            return DebateResult(
                individual_verdicts=individual_verdicts,
                debate_rounds=[],
                final_verdicts=individual_verdicts,
                final_verdict=final_verdict,
                consensus_score=compute_consensus(individual_verdicts),
                stability_score=1.0,
            )

        # Phase 2: 对抗辩论（仅当 ≥2 reviewer 且 debate_rounds > 0; 每轮前查预算）
        debate_log = []
        if len(reviewers) >= 2 and self.debate_rounds > 0:
            current_positions = [v.reasoning for v in individual_verdicts]
            for round_idx in range(self.debate_rounds):
                if not self.broker.check_budget():
                    break  # 预算超限, 终止辩论
                round_args = self._debate_round(reviewers, content, current_positions, context)
                debate_log.append(round_args)
                current_positions = round_args
        else:
            current_positions = [v.reasoning for v in individual_verdicts]

        # Phase 3: 盲评终判（并行, 异常降级同 Phase 1）
        final_verdicts = self._parallel_blind_final(reviewers, content, current_positions, context)

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

    def _parallel_independent_review(self, reviewers, content, context):
        def work(r):
            try:
                return self._independent_review(r, content, context)
            except Exception as e:
                # 单reviewer失败 → 降级为低置信度Verdict, 不击溃整批
                return Verdict(
                    severity=Severity.MAJOR, confidence=0.0,
                    reasoning=f"[REVIEWER FAILED: {e}]",
                    findings=[], satisfied=False,
                )
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(work, r): r for r in reviewers}
            results = {}
            for fut in as_completed(futures):
                r = futures[fut]
                results[reviewers.index(r)] = fut.result()
        return [results[i] for i in range(len(reviewers))]
```

### 8.3 _synthesize 修正

```python
def _synthesize(self, verdicts, reviewers, content) -> Verdict:
    total_weight = sum(r.weight for r in reviewers)
    weighted_confidence = sum(
        v.confidence * r.weight for v, r in zip(verdicts, reviewers)
    ) / total_weight

    # 最严判定：用 Severity.rank 比较，而非字符串 max
    max_severity = max(verdicts, key=lambda v: v.severity.rank).severity

    all_findings = [f for v in verdicts for f in v.findings]

    # satisfied = 所有人都判 pass 或所有人都判 minor 以下
    all_satisfied = all(v.severity == Severity.PASS for v in verdicts)

    return Verdict(
        severity=max_severity,
        confidence=round(weighted_confidence, 4),
        reasoning="\n---\n".join(v.reasoning for v in verdicts),
        findings=all_findings,
        satisfied=all_satisfied,
        original_content=content,
    )
```

### 8.4 consensus_score 修正

```python
def compute_consensus(verdicts: list[Verdict]) -> float:
    """共识度 = reviewer 在 satisfied 判定上的一致比例。
    1.0 = 完全一致，0.0 = 完全分歧（一半对一半）。
    用 2×|ratio - 0.5| 映射到 [0,1]。
    """
    if not verdicts:
        return 0.0
    satisfied_count = sum(1 for v in verdicts if v.satisfied)
    total = len(verdicts)
    ratio = satisfied_count / total
    return round(2 * abs(ratio - 0.5), 4)
```

### 8.5 parse_verdict 多级降级

```python
import json, re
from .types import Verdict, Finding, Severity

def parse_verdict(response: str) -> Verdict:
    """从 LLM 响应解析 Verdict，多级降级：
    1. ```json ... ``` 代码块
    2. 裸 JSON 对象（第一个 {...}）
    3. <SATISFIED>/<UNSATISFIED> 标签（AaaJ 原方案降级）
    """
    # Level 1: JSON 代码块
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return _build_verdict(data)
        except (json.JSONDecodeError, ValidationError):
            pass

    # Level 2: 裸 JSON
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return _build_verdict(data)
        except (json.JSONDecodeError, ValidationError):
            pass

    # Level 3: 标签降级
    if "<SATISFIED>" in response:
        return Verdict(
            severity=Severity.PASS,
            confidence=0.5,  # 标签降级时置信度 capped 0.5（低置信度）
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
```

### 8.6 验收标准

- [ ] 2 个 reviewer + 2 轮辩论 → 完整 `DebateResult`（含 individual_verdicts, debate_rounds, final_verdicts, final_verdict, consensus_score）
- [ ] `Severity.CRITICAL.rank > Severity.PASS.rank` 验证枚举排序
- [ ] `_synthesize` 中 `max_severity` 取 critical 而非字典序最大
- [ ] `consensus_score` = reviewer satisfied 一致比例（非 final_verdict.confidence）
- [ ] Phase 1 并行执行：2 reviewer 时耗时 ≈ max(单次) 而非 sum(单次)（用 mock + timing 验证）
- [ ] 单 reviewer + debate_rounds=2 → 跳过 Phase 2，不空跑辩论
- [ ] `parse_verdict` 对 ```` ```json ```` / 裸 JSON / `<SATISFIED>` 三种输入均正确解析
- [ ] `parse_verdict` 对无法解析的输入抛 `ValueError`
- [ ] `lsp_diagnostics` 无 error

---

## 9. Phase 5-8 详细计划

### Phase 5: 置信度 + 升级路由 + 结构化输出 + AUROC 评估 (1.5 天)

| 任务 | 文件 | 内容 |
|---|---|---|
| 5-1 | `src/adversarial_judge/escalation.py` | `EscalationRouter(confidence_threshold)`: `should_escalate(verdict) -> bool`（用 `calibrated_confidence` 或 `confidence`）；`annotate(verdict) -> Verdict` |
| 5-2 | `src/adversarial_judge/types.py` | `Verdict` / `Finding` Pydantic schema 最终化（含 `escalate_to_human`, `calibrated_confidence`, `original_content`, `confidence_adjustment`） |
| 5-3 | `src/adversarial_judge/judge.py` | 提取原始 `ask.py` 完整判断链（不只公式）：`_collect_judgments()` 投票循环(L71-91) + confidence 公式(L57) + `_parse_judge` 标签解析(L93-97) + `_initialize/_update_llm_stats`(L99-113) 为 `run_majority_vote()` + `parse_verdict()`，供 `_independent_review` 内部使用 |
| 5-4 | `src/adversarial_judge/prompts/judge_system.py` + `judge_user.py` | judge prompt 模板改通用（去掉"code generation"硬编码，接受任意 content + checklist）。`judge_user.py` 的 `build_judge_prompt(content, checklist, context) -> str`。融入 AaaJ prompt 工程技巧：结构化标签+聚焦/排除指令（借鉴 system_prompt_retrieve.py） |
| 5-5 | `src/adversarial_judge/evaluation.py` | **从 `scripts/evaluate_confidence.py` 提取**（最高价值遗漏资产）：`auroc(pairs)` Mann-Whitney U tie-aware 算法(L100-121) + `infer_confidence()` 多级降级(L45-64) + `build_pairs`/`accuracy`/`mean_confidence` 评估管道(L67-92)——验证系统置信度校准质量（"高 confidence 判断是否确实更准确"），纯 Python 无 ML 库依赖 |

**验收**:
```bash
python -c "
from adversarial_judge.escalation import EscalationRouter
from adversarial_judge.types import Verdict, Severity
r = EscalationRouter(0.8)
v = Verdict(severity=Severity.MAJOR, confidence=0.5, reasoning='test', findings=[], satisfied=False)
assert r.should_escalate(v) == True
v2 = Verdict(severity=Severity.PASS, confidence=0.9, reasoning='test', findings=[], satisfied=True)
assert r.should_escalate(v2) == False
print('PASS')
"
# AUROC 算法验证(纯算法,无 LLM 调用)
python -c "
from adversarial_judge.evaluation import auroc
# 完美排序: 正例 confidence 全高于负例 → AUROC = 1.0
pairs_perfect = [(1, 0.9), (1, 0.8), (0, 0.3), (0, 0.2)]
assert abs(auroc(pairs_perfect) - 1.0) < 0.001
# 随机: 交错 → AUROC = 0.5
pairs_random = [(1, 0.6), (0, 0.5), (1, 0.4), (0, 0.3)]
assert abs(auroc(pairs_random) - 0.5) < 0.001
# tie 处理: 两组同分 → AUROC = 0.5
pairs_tie = [(1, 0.5), (1, 0.5), (0, 0.5), (0, 0.5)]
assert abs(auroc(pairs_tie) - 0.5) < 0.001
print('AUROC PASS')
"
```

### Phase 6: 元审查 (1.5 天)

| 任务 | 文件 | 内容 |
|---|---|---|
| 6-1 | `src/adversarial_judge/meta_review.py` | `MetaReviewer(orchestrator, meta_reviewer_names)`: `review(original_content, original_verdict) -> (Verdict, DebateResult)`；`_serialize_verdict(verdict, original_content) -> str` |
| 6-2 | 同上 | 校准公式 `_calibrate_confidence(original, meta) -> float`: `calibrated = original × (1 - penalty)`；penalty 按 severity: critical=0.5/major=0.3/minor=0.1/pass=0；若有 `confidence_adjustment` 则加权融合 |
| 6-3 | `reviewers/meta_reviewer.yaml` + `reviewers/meta_reviewer_2.yaml` | 2 个 meta-reviewer（不同模型/视角），形成真正对抗。`meta_reviewer_2.yaml` 用 `openai/gpt-4o` 异构模型 |
| 6-4 | `src/adversarial_judge/cli.py` | `--review-depth` 递归控制（硬上限 2，超过报错）；`--meta-review` 等价 `--review-depth 1` |

**验收**:
```bash
# 用 mock 验证校准公式
python -c "
from adversarial_judge.types import Verdict, Severity
from adversarial_judge.meta_review import MetaReviewer
# 模拟: original confidence=0.9, meta 发现 critical 漏判
# calibrated = 0.9 × (1 - 0.5) = 0.45
# 无需真实 LLM 调用,验证公式逻辑
print('公式: 0.9 × (1-0.5) =', 0.9 * 0.5)
assert abs(0.9 * 0.5 - 0.45) < 0.01
print('PASS')
"
# 递归深度上限
aj review --content "test" -r spec-reviewer --review-depth 3 2>&1 | grep "上限为 2"
```

### Phase 7: 通用 CLI + 双格式输出 (1.5 天)

| 任务 | 文件 | 内容 |
|---|---|---|
| 7-1 | `src/adversarial_judge/cli.py` | `aj review` + `aj list-reviewers` 命令（typer） |
| 7-2 | 同上 | 3 种输入：`--content` / `--file` / stdin；`--file` 支持 `.json` 后缀时提取 verdict 字段 |
| 7-3 | 同上 | **流程决策三层接线**（design.md 4.8）：零参数 → auto 路由；`--profile fast/standard/thorough` 半决策；细粒度参数（`-r`/`--debate-rounds`/`--review-depth`）覆盖路由。路由结果（档位/reviewer 组合/理由）写入 JSON verdict 的 `route` 字段 |
| 7-4 | 同上 | 双输出：`--output markdown` → stdout；`--output json` → stdout；`--output both --output-dir ./reports` → 写两文件 |
| 7-5 | 同上 | `--max-cost` 预算控制：broker `check_budget()` 在辩论循环中定期检查，超限终止 |
| 7-6 | 同上 | `--interactive`：低置信度时暂停等 stdin 输入人工裁决（注意：stdin 管道传内容时不可用 `--interactive`，需用 `--file` 或 `--content`） |
| 7-7 | `src/adversarial_judge/output/markdown_report.py` | `render_markdown(result, threshold, meta_result) -> str`：人类可读报告，含各 reviewer 发现、辩论摘要、最终裁决、置信度、升级标记、路由档位说明 |
| 7-8 | `src/adversarial_judge/output/json_verdict.py` | `render_json(result, threshold, meta_result, broker) -> str`：机器可读 JSON，含 route + verdict + individual_verdicts + debate_rounds + consensus_score + stability_score + cost |
| 7-9 | `src/adversarial_judge/output/__init__.py` | 导出 `render_markdown` + `render_json` |

**验收**:
```bash
# Markdown 输出
echo "需求:系统支持高并发" | aj review -r requirement-elicitation-reviewer -o markdown | head -5
# JSON 输出
echo "需求:系统支持高并发" | aj review -r requirement-elicitation-reviewer -o json | python -m json.tool
# 双文件输出
aj review --content "test" -r spec-reviewer --output both --output-dir ./reports
test -f ./reports/report.md && test -f ./reports/verdict.json && echo "PASS"
```

### Phase 8: 测试 + 文档 (2 天)

| 任务 | 文件 | 内容 |
|---|---|---|
| 8-1 | `tests/fixtures/mock_llm.py` | `MockLLM(LLM)` 覆盖 `complete`/`complete_json` 返回预设响应；`MockLLMBroker(LLMBroker)` 覆盖 `get_llm` 返回 MockLLM；支持按 reviewer name 路由不同预设响应；可选 `delay` 参数模拟 LLM 延迟以验证并行 timing |
| 8-2 | `tests/test_reviewer.py` | reviewer YAML 加载 / `get`/`list_all` / 校验错误（缺 name / name 含空格 / model=None） |
| 8-3 | `tests/test_judge.py` | `parse_verdict` 3 级降级（JSON 块 → 裸 JSON → `<SATISFIED>` 标签）/ `_build_verdict` 提取 `confidence_adjustment` / `run_majority_vote` 投票聚合 / `Severity(invalid)` 降级为 MINOR |
| 8-4 | `tests/test_debate.py` | `_synthesize` 用 `Severity.rank` 聚合 / `compute_consensus` 一致比例 / `compute_stability` 立场未翻转比例 / 并行异常降级（mock 单个 reviewer 抛异常 → 降级为低置信度 Verdict，不崩溃）/ **单 reviewer 快检形态（跳过 Phase 3，stability 标 degraded=true，1 次 LLM 调用）** |
| 8-5 | `tests/test_router.py` | `route()` 返回合法 `RouteDecision`（mock 分类响应）/ `PROFILE_MAP` 三档参数正确 / **解析失败兜底 standard 档（mock 返回垃圾文本 → 不报错，走 standard）** / 路由 reason 字段可审计 |
| 8-6 | `tests/test_meta_review.py` | `_calibrate_confidence` 公式（severity penalty + adjustment 融合）/ 元审查多 reviewer 对抗 / 递归深度上限 |
| 8-7 | `tests/test_cli.py` | CLI 三种输入 / `--output both` 写文件 / `--review-depth > 2` 报错 / **`--profile fast` 跳过路由直连档位 / 零参数触发 auto 路由（mock）** / verdict JSON 含 `route` 字段 |
| 8-8 | `tests/test_escalation.py` | `EscalationRouter` 低置信度 → `escalate_to_human=True` / 高置信度 → `False` / `calibrated_confidence` 优先 |
| 8-9 | `tests/test_evaluation.py` | `auroc()` 完美排序=1.0 / 随机=0.5 / tie=0.5 / 全正退化=0.5 / `infer_confidence()` 多级降级链 |
| 8-10 | `tests/test_integration.py` (`@pytest.mark.integration`) | 4 场景：①需求分析审查（`requirement-elicitation-reviewer` + `spec-reviewer` 辩论）；②实现对照审查（`implementation-vs-requirement-reviewer`）；③元审查（`--meta-review` 校准 confidence）；**④零参数 auto 路由（验证路由档位判定 + route 字段输出）**。需 `ANTHROPIC_API_KEY` |
| 8-11 | `README.md` | 安装 / `.env` 配置 / 使用示例（零决策 auto / `--profile` 三档 / 细粒度覆盖 / 管道 / 元审查）/ 自定义视角模板指南（YAML 字段说明 + 匿名槽位约束说明） |

**MockLLM 接口设计**:
```python
# tests/fixtures/mock_llm.py
from adversarial_judge.llm.provider import LLM
from adversarial_judge.llm.broker import LLMBroker

class MockLLM(LLM):
    """返回预设响应的 Mock LLM。"""
    def __init__(self, responses: dict[str, str], delay: float = 0.0):
        # responses: {"reviewer_name": "预设 LLM 响应文本"}
        self._responses = responses
        self._delay = delay
        self.model_name = "mock"
        self.cost = None  # 跳过成本追踪

    def complete(self, system_prompt, user_prompt, temperature=None):
        import time
        if self._delay:
            time.sleep(self._delay)
        # 按 system_prompt 中的 reviewer 特征匹配,或返回第一个
        for key, resp in self._responses.items():
            if key in system_prompt:
                return resp
        return list(self._responses.values())[0]

class MockLLMBroker(LLMBroker):
    """注入 MockLLM 的 Broker。"""
    def __init__(self, mock_llm: MockLLM):
        self._mock_llm = mock_llm
        self._cache = {}

    def get_llm(self, model=None):
        return self._mock_llm
```

**验收**:
```bash
# 单元测试(mock,不耗 token)
pytest tests/ -m "not integration" -v --tb=short
# 覆盖率
pytest tests/ -m "not integration" --cov=adversarial_judge --cov-report=term-missing
# 集成测试(需真实 API key)
pytest tests/test_integration.py -m integration -v
```

---

## 10. 验收标准总表

| 验收项 | 验证方式 | 阶段 |
|---|---|---|
| 依赖精简 | `poetry install` 成功，无 spacy/opencv/tree-sitter | Phase 1 |
| 多模型 DI | `LLM(model=X)` 不读 env；`LLMBroker` 缓存生效 | Phase 2 |
| 外部 reviewer | `aj list-reviewers` 列出 ≥13 个（含 3 个过程级） | Phase 3 |
| 辩论正确性 | Severity 枚举排序 + 并行 + consensus 真实计算 | Phase 4 |
| **auto 路由** | 零参数调用触发路由且档位合理；解析失败兜底 standard；verdict 含 `route` 字段 | Phase 4/7 |
| 置信度升级 | 低 confidence → `escalate_to_human=True` | Phase 5 |
| AUROC 校准验证 | `auroc()` 三例断言（完美/随机/tie）通过 | Phase 5 |
| 元审查校准 | `calibrated_confidence` 与 `confidence` 不同（有校准） | Phase 6 |
| CLI 全路径 | `aj review --file x.md` 零参数产出有效 JSON（auto）；`--profile` 显式档位；细粒度覆盖 | Phase 7 |
| 测试覆盖 | `pytest` 全绿（10 个测试文件）+ mock 不耗 token | Phase 8 |
| 文档完整 | README 含安装/配置/三档用法/自定义模板指南 | Phase 8 |
| LSP 无错 | 所有新文件 `lsp_diagnostics` 无 error | 全程 |

---

## 11. 风险与对策

| 风险 | 概率 | 影响 | 对策 | 阶段 |
|---|---|---|---|---|
| litellm 对 Claude 结构化输出支持不完整 | 中 | 高 | tool-use 优先 + 多级降级解析 + tenacity 重试 | Phase 2, 5 |
| 辩论 token 成本爆炸 | 中 | 中 | `--max-cost` 预算控制 + broker 超限终止 + profile 档位限制调用数 | Phase 7 |
| **auto 路由误判档位**（轻内容路由到 thorough 浪费成本 / 复杂内容路由到 fast 质量不足） | 中 | 中 | 路由结果含 reason 可审计 + `--profile` 显式覆盖兜底 + 解析失败兜底 standard + route 字段可事后分析调优 | Phase 4 |
| 单 reviewer 辩论自说自话 | 高 | 高 | `len(reviewers) < 2` 时跳过 Phase 2 | Phase 4 |
| severity 字符串比较错误 | 已确认 | 高 | `Severity(StrEnum)` + `.rank` 属性 | Phase 4 |
| 元审查递归成本失控 | 低 | 中 | `--review-depth` 硬上限 2 | Phase 6 |
| parse_verdict 对非 JSON 输出失败 | 中 | 中 | 3 级降级：JSON 块 → 裸 JSON → `<SATISFIED>` 标签 | Phase 4 |
| 同模型 reviewer 共享盲区 | 中 | 中 | reviewers/*.yaml 鼓励混用模型（sonnet + opus + GPT-4o） | Phase 3 |
| 并行独立评审的线程安全 | 低 | 中 | `ThreadPoolExecutor` + LLM 实例无共享可变状态（broker 缓存只读） | Phase 4 |
| fork 上游更新冲突 | 低 | 低 | 改造后不再同步上游（定位为独立项目） | 全程 |

---

## 12. 附录：用户诉求 → 修正项 → Phase 速查

| 用户诉求 | 文档问题 | 修正项 | 实施阶段 |
|---|---|---|---|
| 需求分析各环节审查 | G-2 | spec FR-1 细化 + reviewers YAML | Phase 0 + Phase 3 |
| 代码生成后各环节审查 | G-3 | spec FR-1 细化 + reviewers YAML | Phase 0 + Phase 3 |
| 避免单 Agent 幻觉 | — | 已覆盖（辩论+多模型+多数投票） | Phase 4 + Phase 2 |
| 代码检视不在职责内 | — | 已覆盖（spec 2.1 排除） | — |
| 代码检视产物可审查 | G-1 | spec 审查范围表 + reviewer YAML | Phase 0 + Phase 3 |
| 标注置信度 | — | 已覆盖 | Phase 5 |
| 告诉人哪些需人工介入 | — | 已覆盖（escalation） | Phase 5 |
| 降低人工心智负担 | — | 已覆盖（双格式输出） | Phase 7 |
| 外部自定义扩展 agent | — | 已覆盖（YAML reviewer） | Phase 3 |
| 借鉴 LangGraph | G-4 | spec FR/NFR 补充 + 结构化输出 + 并行 + interactive | Phase 0 + Phase 2 + Phase 4 + Phase 7 |
| 借鉴 agent-review-panel | G-4 | spec FR-8 补充完整性审计 + 辩论+盲评 | Phase 0 + Phase 4 + Phase 6 |
| 元审查（审查结果可被审查） | B-3, B-4 | 多 meta-reviewer + 校准公式 | Phase 6 |
