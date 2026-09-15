# agent-judges

多 agent 辩论式 AI 产出审计系统。对 AI 生成的需求文档、规格、设计、代码、测试计划、检视报告等产出物进行对抗审查——N 个 reviewer 独立评审 → 对抗辩论 → 盲评终判 → 裁决合成，置信度低于阈值时自动标记人工升级。

## 这是什么

单 Agent 审查有幻觉、遗漏、过度自信等问题。本系统通过**多 reviewer 辩论 + 确定性状态机编排**解决：

- **4 阶段辩论**：独立评审（并行）→ 1-3 轮对抗辩论 → 盲评终判 → 加权裁决合成
- **渐进式门控**：零参数调用时，哨兵单审 → 早停或面板扩张 → 强度升级，自动匹配内容复杂度
- **scene 路由**：通过 `--scene` 声明审查场景（document/code/review-report），引擎按 reviewer 的 `scenes` 元字段自动筛选匹配的审查视角
- **元审查**：审查结果本身可被再次审查，通过显式校准公式修正置信度
- **graphify 证据注入**：`--scene code` 时自动从 graphify 知识图谱提取调用关系证据，注入 reviewer 上下文（无 graphify 时静默降级，不影响运行）
- **匿名槽位 + 视角注入**：只安装一个匿名 reviewer Agent，persona 由引擎编译进 task prompt

**不做什么**：代码风格、命名规范、设计模式、性能微优化（传统 code review 范畴）。

## 宿主集成（推荐用法）

主流用法是在 **CodeAgent / Claude Code / OpenCode 会话内**触发审查：LLM 模型、凭证、额度全部来自宿主已有配置，用户零模型配置。

```bash
# 一次性安装: judge-manager + 匿名 reviewer Agent 装入宿主
agent-judges install                      # 默认 codeagent 平台(.cac 目录)
agent-judges install --platform opencode --project   # 显式指定/装项目级
agent-judges install --platform claude-code          # claude-code 平台
```

安装后只装 2 个 Agent：

- **judge-manager**（对外入口）：机械执行驱动协议——拉起匿名 reviewer Agent、逐字传 prompt、结果落盘、调引擎推进、终态汇报。不做任何流程决策。
- **reviewer**（匿名槽位）：无 persona 的通用审查 Agent。引擎在发出任务时将 reviewer persona + 系统固定审查框架编译进 task prompt，judge-manager 逐字传给匿名 reviewer 执行。

```
# 在宿主会话里直接说:
"帮我对抗审查这份 spec.md"
→ 宿主委派 judge-manager → 引擎驱动匿名 reviewer 辩论 → 汇报 verdict
```

**平台支持**：`codeagent`（默认，`.cac` 目录）、`claude-code`（`.claude` 目录）、`opencode`（`.opencode` 目录）。`--host` 为 `--platform` 的向后兼容别名。Agent 统一装到 `judges/` 子目录，与用户自有 Agent 区分。

## 安装

```bash
git clone <repo>
cd agent-judges
pip install -e .
# 或: poetry install
```

## 快速开始

### 宿主会话内（推荐，零配置）

安装后直接在宿主会话中触发，LLM 能力来自宿主环境。

### CLI 直连模式（调试 / CI）

加 `--llm litellm` 走引擎进程内直连，需 API key（`.env.sample` → `.env`）：

```bash
# 列出内置视角模板与 skill
agent-judges list-reviewers
agent-judges list-skills

# 零决策全自动: 渐进式审查自动选档(--scene 按后缀推断, .md → document)
agent-judges review --file ./spec.md --llm litellm

# 显式指定审查场景
agent-judges review --file ./spec.md --llm litellm --scene document
agent-judges review --file ./auth.py --llm litellm --scene code
agent-judges review --file ./review.json --llm litellm --scene review-report

# 显式选档
agent-judges review --file ./spec.md --llm litellm --scene document --profile fast
agent-judges review --file ./spec.md --llm litellm --scene document --profile standard
agent-judges review --file ./spec.md --llm litellm --scene document --profile thorough

# 细粒度参数
agent-judges review --llm litellm --scene document --content "系统需要支持高并发..." \
  --debate-rounds 2 --threshold 0.8

# 管道接入
cat requirements.md | agent-judges review --llm litellm --scene document -o json | jq '.verdict.escalate_to_human'

# 元审查: 审查上一轮的审查结果
agent-judges review --llm litellm --file verdict.json --scene document --meta-review -o json > meta_verdict.json

# 双格式输出到目录
agent-judges review --llm litellm --file ./spec.md --scene document --output both --output-dir ./reports

# 预算控制 + 本地网关
agent-judges review --llm litellm --file ./spec.md --scene document --max-cost 0.50
agent-judges review --llm litellm --file ./spec.md --scene document --base-url http://localhost:11434

# 低置信度时暂停等待人工裁决
agent-judges review --llm litellm --file ./spec.md --scene document --interactive
```

## 审查场景（--scene）

`--scene` 声明审查场景，引擎按 reviewer 模板的 `scenes` 元字段自动筛选匹配的审查视角。不传时按文件后缀推断。

| 场景 | 适用产出物 | graphify | reviewer 来源 |
|---|---|---|---|
| `document` | 需求文档、规格、设计文档、测试计划、README | 不激活 | spec-reviewer / design-reviewer / requirement-* / documentation-reviewer 等 |
| `code` | 源代码、测试代码、部署配置（Dockerfile/IaC） | **激活** | implementation-vs-requirement-reviewer / unit-test-reviewer / dangerous-operation-scanner 等 |
| `review-report` | 外部代码检视报告（SonarQube/ESLint/人工 review 产物） | 不激活 | external-code-review-auditor / deception-detector |

后缀 fallback：`.py`/`.ts`/`.go`/`.rs`/`.java` 等 → `code`；`.md`/`.txt`/其他 → `document`。`review-report` 无后缀 fallback，必须显式声明。

## 三档 Profile

| 档位 | reviewer 数 | 辩论轮 | 元审查 | LLM 调用数 | 适用场景 |
|---|---|---|---|---|---|
| **fast** | 1 | 0 | 否 | 1 | 短文本快检、CI 门禁 |
| **standard** | 2 | 1 | 否 | ~6 | 常规文档审查 |
| **thorough** | 3 | 2 | 是 | ~15 | 关键交付物、终审 |

零参数时渐进式门控自动选档：哨兵单审 → 根据分歧程度决定早停（fast）或升级（standard/thorough）。路由结果记录在 JSON verdict 的 `route` 字段中。

## 输出

`--output markdown`（默认）→ stdout 人类可读报告；`--output json` → stdout 机器可读 verdict；`--output both --output-dir DIR` → 写 `report.md` + `verdict.json`。JSON 不输出到 stderr。

```json
{
  "verdict": {
    "severity": "major",
    "confidence": 0.65,
    "calibrated_confidence": 0.455,
    "escalate_to_human": true,
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

`severity` 枚举：critical > major > minor > pass。`calibrated_confidence` 是元审查校准后的置信度，升级判定优先使用。

## 扩展 reviewer

本系统的约束模型是**匿名槽位 + 视角注入**：安装时只有一个匿名 reviewer Agent（无 persona），所有审查视角通过文件定义，引擎在发出任务时将 persona + checklist 编译进 task prompt。**不创建新的 Agent 文件**。用户不直接指定用哪个 reviewer，而是通过 `--scene` 声明场景，引擎按 `scenes` 元字段自动筛选。

### 视角模板（`reviewers/*.md`）

定义"谁来审"——persona + checklist + scenes。复制 `reviewers/custom_example.md` 为新文件即可：

```markdown
---
name: my-security-auditor        # 唯一标识
description: 安全审计视角
scenes: [document, code]          # 适用的场景(可多值)
# model: opus                    # 可选,宿主命名空间模型名(省略=宿主默认)
checklist:                       # 检查清单
  - criteria: 认证与授权路径完整
  - criteria: 敏感数据处理合规
    weight: 0.5                  # checklist 项可单独设权重
skills:                          # 可选:引用 skill(知识注入)
  - owasp-top10
weight: 1.0                      # 聚合权重
majority_vote: 1                 # >1 时同模型多次调用投票(反幻觉)
---

你是一位安全审计专家,从安全视角审查 AI 产出的内容。
关注: 认证授权、数据安全、输入处理、依赖安全。
对每条发现给出 severity / confidence / evidence / suggestion。
```

```bash
# 模板加入 reviewers/ 后,--scene document 或 --scene code 时自动匹配
agent-judges review --file doc.md --scene document
```

### 审查 skill（`skills/*.md` 或 `skills/<name>/SKILL.md`）

定义"用什么知识审"——领域知识包（模式清单、定级基准、few-shot 示例）。纯 LLM 范式，不含工具执行。通过 reviewer 模板的 `skills:` 字段引用，skill body 在 registry 加载时自动注入到 reviewer 的 system_prompt。

内置示例：`dangerous-operation-scanner` 模板引用 `dangerous-operations` skill。

skill 文件格式：

```markdown
---
name: my-compliance-skill
description: 金融合规审查知识包
checklist:            # 可选:作为检查清单
  - criteria: "敏感数据分类分级已落实"
---

# 审查知识正文

(领域 rubric、模式清单、定级基准、few-shot 示例……)
```

```bash
agent-judges list-skills                        # 查看可用 skill
```

### scenes 字段

reviewer 模板的 `scenes` 字段声明适用的审查场景，支持多值：

```yaml
scenes: [document]           # 仅文档场景
scenes: [code]               # 仅代码场景
scenes: [document, code]     # 跨场景
# 不设置 = 不参与 scene 路由（如 meta-reviewer，系统内部调用）
```

### model 字段说明

视角模板的 `model` 字段使用宿主命名空间：

- **claude 系宿主**：仅 Anthropic 模型（`opus`/`sonnet`/完整 ID）
- **opencode 系宿主**：`provider/model`（已配置任意 provider，含自定义网关）
- **省略**：宿主默认模型
- **异构面板**（不同 reviewer 用不同模型）：使用 `--llm litellm` 直连模式

### graphify 证据注入

`--scene code` 时，引擎自动检测 graphify CLI 和 `.graph/graph.json`：

- **存在时**：执行 `graphify query` + `graphify explain`，把调用关系/依赖信息追加到 reviewer context，供验证 finding 时参考
- **不存在时**：静默跳过，不影响运行（三层降级：CLI 检测 → 异常捕获 → None 透传）

`--scene document` 和 `--scene review-report` 不会触发 graphify。

## 内置视角模板

| 模板 | scenes | 覆盖场景 |
|---|---|---|
| `spec-reviewer` | document | 需求与规格文档（完整性、可追溯性、契约、歧义消除、MECE） |
| `design-reviewer` | document | 设计文档（架构决策、风险消解、失败模式） |
| `test-plan-reviewer` | document | 测试计划（测试分层、回归策略、数据环境） |
| `documentation-reviewer` | document | 文档（API 文档/README，示例可运行性、参数完整性） |
| `deception-detector` | document, review-report | 欺骗检测 + 过程合规（claim vs 证据、执行痕迹） |
| `implementation-vs-requirement-reviewer` | code | 代码是否满足需求（非代码风格） |
| `unit-test-reviewer` | code | 单元测试（断言有效性、mock 合理性、测试独立性） |
| `integration-test-reviewer` | code | 集成测试（接口契约、超时/重试/幂等、环境策略） |
| `deployment-config-reviewer` | code | 部署配置（Dockerfile/IaC 安全基线、可运维性） |
| `dangerous-operation-scanner` | code | 危险操作扫描（引用 skill） |
| `external-code-review-auditor` | review-report | 外部代码检视报告审查（覆盖度、误报、漏报） |
| `meta-reviewer` / `meta-reviewer-2` | —（系统内部） | 元审查 |

## 内置 skill

| skill | 用途 |
|---|---|
| `dangerous-operations` | 危险操作模式清单 + 语义判定指引（被模板引用） |
| `owasp-top10` | OWASP Top 10 安全审查知识包 |
| `api-contract-review` | API 契约完整性审查 |

## 开发

```bash
pytest tests/ -m "not integration" -v    # 单元测试(mock LLM,零 token)
mypy src/adversarial_judge               # 类型检查
pytest tests/test_e2e.py -v              # 端到端(固定应答驱动,零 token)
```

设计文档：[docs/spec.md](docs/spec.md) · [docs/design.md](docs/design.md)
