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

```bash
# 在宿主会话里直接说:
"帮我对抗审查这份 spec.md"
→ 宿主委派 judge-manager → 引擎驱动匿名 reviewer 辩论 → 汇报 verdict
```

judge-manager 支持自然语言触发，也可以直接指定参数：

```
"审查这份 spec.md，用 thorough 档"
"审查 auth.py，--scene code"
"审查这份检视报告 review.json，--scene review-report"
"零参数全自动审查 requirements.md"
```

### 命令行工具

`agent-judges` CLI 提供安装、列出视角模板、列出 skill 等辅助命令：

```bash
agent-judges install                              # 安装到宿主(默认 codeagent 平台)
agent-judges install --platform claude-code       # 安装到 claude-code
agent-judges install --platform opencode --project  # 安装到 opencode 项目级
agent-judges list-reviewers                       # 列出内置视角模板
agent-judges list-skills                          # 列出内置 skill
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

安装时只装 1 个匿名 reviewer Agent（无 persona）。所有审查视角通过文件定义，引擎编译进 task prompt。**不创建新的 Agent 文件**。

扩展方式有两种，可以单独或组合使用：

### 方式一：新增视角模板（定义"谁来审"）

在 `reviewers/` 目录下新建 `.md` 文件（复制 `reviewers/custom_example.md` 改即可）。模板包含 persona（审查者人设）+ checklist（检查清单）+ scenes（适用场景）。引擎按 `--scene` 自动筛选匹配的模板。

```markdown
---
name: my-security-auditor        # 唯一标识
description: 安全审计视角
scenes: [document, code]          # 声明适用场景(可多值)
# model: opus                    # 可选,宿主命名空间模型名(省略=宿主默认)
checklist:                       # 检查清单
  - criteria: 认证与授权路径完整
  - criteria: 敏感数据处理合规
    weight: 0.5                  # checklist 项可单独设权重
skills:                          # 可选:引用 skill 知识包(见方式二)
  - owasp-top10
weight: 1.0                      # 聚合权重
majority_vote: 1                 # >1 时同模型多次调用投票(反幻觉)
---

你是一位安全审计专家,从安全视角审查 AI 产出的内容。
关注: 认证授权、数据安全、输入处理、依赖安全。
对每条发现给出 severity / confidence / evidence / suggestion。
```

```bash
# 文件放入 reviewers/ 后,引擎按 --scene 自动匹配,无需指定 reviewer 名
agent-judges review --file doc.md --scene document
```

> **系统固定框架**：无论 persona 怎么写，引擎会在 persona 外层套一段不可覆盖的行为约束（客观引用证据、severity 与证据强度匹配、推理可追溯）。你只需写"审查什么、怎么审"，不必操心输出格式和辩论流程——这些由系统固定控制。

### 方式二：新增审查 skill（定义"用什么知识审"）

在 `skills/` 目录下新建知识包文件。skill 是纯领域知识（模式清单、定级基准、few-shot 示例），不含工具执行。两种文件格式任选：

```
skills/
  my-compliance.md            # 单文件格式
  owasp-top10/SKILL.md        # 目录格式(适合带附加资源的知识包)
```

skill 通过 reviewer 模板的 `skills:` 字段引用。引擎加载时将 skill 正文自动拼接到该 reviewer 的 persona 后面，reviewer 即获得该领域知识：

```markdown
---
name: my-compliance-skill
description: 金融合规审查知识包
checklist:                     # 可选:作为检查清单注入引用方
  - criteria: "敏感数据分类分级已落实"
---

# 审查知识正文

(领域 rubric、模式清单、定级基准、few-shot 示例……)
```

```bash
agent-judges list-skills                        # 查看可用 skill
```

内置示例：`dangerous-operation-scanner` 模板引用 `dangerous-operations` skill 获取危险操作模式清单和语义判定指引。

### 自定义目录路径

默认从 `./reviewers/` 和 `./skills/` 加载。通过 CLI 参数指定自定义路径：

```bash
agent-judges review --file doc.md --scene document \
  --reviewers-dir ./my-reviewers \
  --skills-dir ./my-skills
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
mypy src/agent_judges               # 类型检查
pytest tests/test_e2e.py -v              # 端到端(固定应答驱动,零 token)
```

设计文档：[docs/spec.md](docs/spec.md) · [docs/design.md](docs/design.md)
