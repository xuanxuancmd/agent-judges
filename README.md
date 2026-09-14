# adversarial-judge (agent-judges)

一个通用的、可外部定义 reviewer 与 skill 的、多 agent 辩论式的、置信度驱动人工升级的、且自身可递归审查的 AI 产出审计系统。

> 受 [Agent-as-a-Judge](https://arxiv.org/pdf/2410.10934) (ICML 2025) 启发的重写。MIT 许可。

## 这是什么

所有 AI 产出的东西（需求文档、规格、设计、代码、测试计划、检视报告…）都需要被另一个（组）AI **对抗审查**一遍——单 Agent 有幻觉、遗漏、过度自信等问题。本系统提供：

- **4 阶段辩论编排**：N 个 reviewer 独立评审（并行）→ 1-3 轮对抗辩论 → 盲评终判 → 裁决合成
- **MD 视角模板 + SKILL.md 审查 skill**：审查者与知识包均通过外部文件定义，无需改代码
- **多模型混用**：不同 reviewer 可指定不同 LLM（Claude sonnet + opus + GPT-4o），避免同模型共享盲区
- **置信度 + 人工升级**：`confidence < 阈值 → escalate_to_human: true`
- **元审查**：审查结果本身可被再次审查，通过显式校准公式修正置信度
- **auto 路由**：零参数调用，一次轻量 LLM 分类自动选档位与 reviewer 组合

**不做什么**：代码风格、命名规范、设计模式、性能微优化（传统 code review 范畴）。但外部代码检视工具（SonarQube/ESLint/人工 review）的**产物**可以被本系统审查。

## 宿主集成（推荐用法，v2）

主流用法是在 **Claude Code / OpenCode 会话内**触发审查：LLM 模型、凭证、额度全部来自宿主已有配置，用户零模型配置。

```bash
# 一次性安装:judge-manager + 全部 reviewer Agent 装入宿主
agent-judges install                      # 自动探测宿主(claude-code/opencode)
agent-judges install --host opencode --project   # 显式指定/装项目级

# 之后在宿主会话里直接说:
#   "帮我对抗审查这份 spec.md"
# → 宿主委派 judge-manager → 经 agent-judges 引擎驱动多 reviewer 辩论 → 汇报
```

- **judge-manager**（入口 Agent）：机械执行驱动协议（拉起 reviewer Agent / 逐字传 prompt / 结果落盘 / 调引擎推进），不做任何流程决策
- **编排权在引擎**：渐进式门控、4 阶段辩论、裁决合成全部由 `agent-judges` 的 prepare/resume 状态机确定性推进（运行目录可审计、可断点续跑）
- **reviewer 模型**：各 reviewer 的 `model` 字段写宿主命名空间（claude 系 `opus`/`sonnet`；opencode 系 `provider/model`），省略 = 宿主默认模型；异构面板保留
- **安装布局**：所有 Agent 统一装到 `judges/` 子目录（claude-code：`.claude/agents/judges/`；opencode：`.opencode/agents/judges/`），与用户自有 Agent 区分。命名差异：claude-code 以 frontmatter `name` 为名（`spec-reviewer`）；opencode 以文件路径为名（`judges/spec-reviewer`），judge-manager 驱动协议已内置前缀映射
- **CLI 直连模式**（`--llm litellm`）：引擎进程内直接调 LLM API，用于 CI/裸机/调试；此时凭证经环境变量（见下文）

## 安装

```bash
git clone <repo>
cd agent-judges
pip install poetry
poetry install
# 或: pip install -e .
```

配置 API key（`.env.sample` → `.env`）：

```bash
cp .env.sample .env
# ANTHROPIC_API_KEY="sk-ant-***"
# OPENAI_API_KEY="sk-***"     # meta-reviewer-2 默认用 GPT-4o
```

默认模型为 `anthropic/claude-sonnet-4-20250514`（`--model` 可覆盖；`--base-url` 指向本地/代理网关）。通过 litellm 支持任意模型。

## 从 Claude Code / OpenCode 中调用（凭证继承）

`agent-judges` 是被编码 agent 通过 shell 调用的质量关卡，**LLM 凭证优先从调用方会话环境继承**，解析顺序：显式参数 > 环境变量 > litellm 内部回退（见 `llm/credentials.py`）。

### Claude Code

| 会话认证方式 | 能否复用 | 说明 |
|---|---|---|
| `ANTHROPIC_API_KEY`（API key 认证） | ✅ 自动继承 | 子进程继承环境变量 |
| `ANTHROPIC_AUTH_TOKEN`（网关/代理 Bearer） | ✅ 自动继承 | 同上 |
| `claude setup-token` 导出 `CLAUDE_CODE_OAUTH_TOKEN` | ✅ 自动继承 | litellm 识别 `sk-ant-oat*` 前缀并走 Bearer + OAuth beta 头 |
| Pro/Max 订阅登录（`/login`） | ❌ 不可复用 | OAuth 凭证存储在 `~/.claude/.credentials.json`，**不导出**到子进程环境；请改用 `claude setup-token` 或设置 `ANTHROPIC_API_KEY` |

> 注意：宿主设置 `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` 时，所有凭证会从子进程环境中剥离，`agent-judges` 无法继承——此时需在 `.env` 显式配置或经本地网关（`--base-url`）访问。

```bash
# Claude Code 会话内（bash 工具直接调用，凭证从会话环境继承）:
agent-judges review --file ./spec.md -r spec-reviewer -o json | jq .verdict.escalate_to_human
```

### OpenCode

OpenCode 的 provider 凭证存储在 `~/.local/share/opencode/auth.json`，**不会**导出为子进程环境变量；官方 `opencode serve` 是管理 API，不是 Anthropic/OpenAI 线协议代理。两种接法：

```bash
# 方式 1（推荐）: 安装社区插件 opencode-llm-proxy
# （本地 127.0.0.1:4010，Anthropic/OpenAI 线协议兼容，转发到 opencode 已配置的 provider）
agent-judges review --file ./spec.md --base-url http://127.0.0.1:4010

# 方式 2: 在启动 opencode 的 shell 中显式 export provider key
# （环境具有传递性：opencode 进程环境中有，其 bash 子进程就能看到）
export ANTHROPIC_API_KEY="sk-ant-***"
```

### 解析顺序速查

- `anthropic/*` 模型：`--base-url`/显式参数 > `ANTHROPIC_API_KEY` > `ANTHROPIC_AUTH_TOKEN` > `CLAUDE_CODE_OAUTH_TOKEN` >（网关）`ANTHROPIC_BASE_URL`
- `openai/*` 模型：`OPENAI_API_KEY` / `OPENAI_BASE_URL`
- 无凭证时 CLI 给出可操作提示（本地模型如 `ollama/*` 不误报）；`meta-reviewer-2`（GPT-4o）需要 `OPENAI_API_KEY`，缺失时该 reviewer 按容错策略降级，不影响整体产出

## 快速开始（CLI 直连调试）

> 以下示例用于 **CLI 直连调试 / CI**。加 `--llm litellm` 走引擎进程内直连（需 API key）。
> 宿主会话内的推荐用法见上方"宿主集成"（零参数、零配置）。

```bash
# 列出 20 个内置视角模板与 3 个内置 skill
agent-judges list-reviewers
agent-judges list-skills

# 零决策全自动(推荐): 渐进式审查自动选档
agent-judges review --file ./spec.md --llm litellm

# 半决策: 显式选档
agent-judges review --file ./spec.md --llm litellm --profile fast      # 快检(1 次调用)
agent-judges review --file ./spec.md --llm litellm --profile standard  # 常规审查(2 reviewer + 1 轮辩论)
agent-judges review --file ./spec.md --llm litellm --profile thorough  # 深审(3 reviewer + 2 轮辩论 + 元审查)

# 全决策: 细粒度参数
agent-judges review --llm litellm --content "我们的系统需要支持高并发..." \
  -r requirement-elicitation-reviewer \
  -r spec-reviewer \
  --debate-rounds 2 \
  --threshold 0.8

# 即席加载 skill 为审查视角(通用匿名 agent 加载用户自定义 skill)
agent-judges review --llm litellm --file api-spec.md -r skill:api-contract-review
agent-judges review --llm litellm --file gateway-config.md -r skill:owasp-top10 --debate-rounds 0

# 管道接入(Claude Code / OpenCode / CI)
cat requirements.md | agent-judges review --llm litellm -r requirement-elicitation-reviewer -o json | jq '.verdict.escalate_to_human'

# 元审查: 审查上一轮的审查结果
agent-judges review --llm litellm --file verdict.json --meta-review -o json > meta_verdict.json

# 双格式输出到目录
agent-judges review --llm litellm --file ./spec.md -r spec-reviewer --output both --output-dir ./reports

# 预算控制 + 强制覆盖模型 + 本地网关(测试用)
agent-judges review --llm litellm --file ./spec.md -r spec-reviewer --override-model openai/gpt-4o --max-cost 0.50
agent-judges review --llm litellm --file ./spec.md -r spec-reviewer --base-url http://localhost:11434

# 低置信度时暂停等待人工裁决
agent-judges review --llm litellm --file ./spec.md -r spec-reviewer --interactive

# 置信度校准评估(验证"高置信度判断是否确实更准确": Accuracy/AUROC)
agent-judges evaluate --predictions verdicts.json --labels human_labels.json
```

## 三档 Profile

| 档位 | reviewer 数 | 辩论轮 | 元审查 | LLM 调用数 | 适用场景 |
|---|---|---|---|---|---|
| **fast** | 1 | 0 | 否 | 1 | 短文本快检、CI 门禁、迭代内自检 |
| **standard** | 2 | 1 | 否 | ~6 | 常规文档审查 |
| **thorough** | 3 | 2 | 是 | ~15 | 关键交付物、终审 |

零参数时 auto 路由（一次轻量 LLM 分类，temp=0，可审计）自动选档；路由结果完整记录在 JSON verdict 的 `route` 字段中。

## 输出

`--output markdown`（默认）→ stdout 人类可读报告；`--output json` → stdout 机器可读 verdict；`--output both --output-dir DIR` → 写 `report.md` + `verdict.json` 两个文件。JSON **不输出到 stderr**（stderr 仅供日志）。

JSON verdict 核心字段：

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

字段说明：`severity` 为枚举（critical > major > minor > pass，显式排序，避免字符串比较错误）；`consensus_score` 是 reviewer 间一致度（非聚合置信度）；`stability_score` 是辩论前后立场稳定性；`calibrated_confidence` 是元审查校准后的置信度（升级判定优先使用）。

## 自定义审查视角模板

系统采用**匿名槽位 + 视角注入**约束模型：你只能注入"审查视角"（persona + checklist），不能自定义辩论行为、输出格式、流程编排——这些由系统固定控制（保证辩论流程兼容）。

复制 `reviewers/custom_example.md` 为新文件，修改后即可使用：

```markdown
---
name: my-security-auditor        # 唯一标识(slug)
description: 安全审计视角
# model: opus                    # 可选,宿主命名空间模型名(省略=宿主默认)
checklist:                       # 检查清单
  - criteria: 认证与授权路径完整
skills:                          # 可选:引用审查 skill(知识注入)
  - owasp-top10
weight: 1.0                      # 聚合权重
majority_vote: 1                 # >1 时同模型多次调用投票(轻量级反幻觉)
---

你是一位安全审计专家……           # persona 正文(审查者人设 + 关注维度)
```

```bash
agent-judges review --llm litellm --file doc.md -r my-security-auditor
```

## 自定义审查 skill

skill 是**知识注入型**的用户自定义审查知识包（SKILL.md 格式，兼容业界 skill 约定；纯 LLM 范式——不含工具执行）。由通用匿名 agent 槽位加载，两种方式：

**方式 1：即席加载**（skill = 完整审查视角）：

```bash
agent-judges review --llm litellm --file api-spec.md -r skill:api-contract-review
```

**方式 2：模板引用**（skill = reviewer 的知识扩展）：见上节 `skills:` 字段。内置示例：`dangerous-operation-scanner` 模板引用 `dangerous-operations` skill（模式清单独立维护，模板只保留 persona）。

skill 文件格式（两种布局：`skills/<name>/SKILL.md` 或 `skills/<name>.md`）：

```markdown
---
name: my-compliance-skill
description: 金融合规审查知识包
checklist:            # 可选:即席加载时作为检查清单
  - criteria: "敏感数据分类分级已落实"
---

# 审查知识正文

(领域 rubric、模式清单、定级基准、few-shot 示例……)
```

```bash
agent-judges list-skills                        # 查看可用 skill
agent-judges review --file x.md -r skill:my-compliance-skill --debate-rounds 0
```

### 内置视角模板（20 个）

| 模板 | 覆盖场景 |
|---|---|
| `requirement-elicitation-reviewer` | 需求收集 |
| `requirement-clarification-reviewer` | 需求澄清（歧义消除、假设记录） |
| `requirement-decomposition-reviewer` | 需求分解（MECE） |
| `requirement-prioritization-reviewer` | 需求优先级（MoSCoW） |
| `requirement-acceptance-reviewer` | 验收标准（可测试性） |
| `spec-reviewer` | 规格文档 |
| `design-reviewer` | 设计文档（opus） |
| `implementation-vs-requirement-reviewer` | 实现对照需求 |
| `unit-test-reviewer` | 单元测试 |
| `integration-test-reviewer` | 集成测试 |
| `test-plan-reviewer` | 测试计划 |
| `deployment-config-reviewer` | 部署配置（Dockerfile/IaC） |
| `documentation-reviewer` | 文档（API 文档/README） |
| `external-code-review-auditor` | 外部代码检视报告审查 |
| `process-compliance-reviewer` | 过程合规（agent 日志） |
| `deception-detector` | 欺骗检测（claim vs 证据） |
| `dangerous-operation-scanner` | 危险操作扫描（引用 skill） |
| `meta-reviewer` / `meta-reviewer-2` | 元审查（Claude + GPT-4o 异构对抗） |
| `custom_example.md` | 自定义模板示例（含字段说明） |

### 内置 skill（3 个）

| skill | 用途 |
|---|---|
| `dangerous-operations` | 危险操作正则模式清单 + 语义判定指引（被模板引用） |
| `owasp-top10` | OWASP Top 10 安全审查知识包（含 checklist，可即席加载） |
| `api-contract-review` | API 契约完整性审查（平铺式示例） |

## 开发

```bash
# 单元测试(mock LLM,不耗 token)
pytest tests/ -m "not integration" -v

# 类型检查
mypy src/adversarial_judge

# 集成测试(需真实 API key)
pytest tests/test_integration.py -m integration -v
```

## E2E 测试（真实需求文档）

`tests/project/` 下提供两组真实需求文档作为审查对象，各含 `spec.md`（规格）+ `plan.md`（执行计划）：

| 项目 | 复杂度 | 内容 |
|---|---|---|
| `todo-app` | 简单 | Todo 列表应用 |
| `graphify-gitnexus` | 复杂 | 在 graphify 图谱基础上对标 GitNexus 补齐能力 |

e2e 用一个**合成 judge-manager 驱动器**（`tests/fixtures/e2e_driver.py`）逐字执行驱动协议：prepare → 读 `tasks/<id>.md` → 应答 → 写 `results/<id>.md` → resume，直到终态。应答器可插拔：固定应答（零 token，验证状态机/门控/辩论/合成/升级全链路）或真实 LLM（验证检视效果）。

```bash
# 自动 · 零 token(默认测试套件内,固定应答驱动全链路)
pytest tests/test_e2e.py -v

# 自动 · 真实 LLM · CI 回退路径(需 API key 凭证,校验 verdict 结构自洽)
pytest tests/test_e2e.py -m integration -v
```

### 手动 · 主路径（宿主驱动，零 API key）

与产品主流场景一致——LLM 能力全部来自宿主（Claude Code / OpenCode）拉起的实体 reviewer Agent，用户零模型配置：

```bash
# 1. 一次性安装: judge-manager + 全部 reviewer Agent 装入宿主(项目级)
agent-judges install --host opencode --project   # 或 --host claude-code

# 2. 新开宿主会话,直接说:
#    "用 judge-manager 对抗审查 tests/project/todo-app/spec.md"
#    → 宿主委派 judge-manager → 机械驱动引擎 → 终态汇报
```

也可在宿主会话中手动驱动（judge-manager 协议的人工版）：`agent-judges review --file <doc>` → 逐个拉起 reviewer 子代理（prompt 取 `<logs_dir>/tasks/<id>.md` **逐字**传递，persona 来自已安装的 Agent 定义）→ 子代理回复**原样**写 `<logs_dir>/results/<id>.md` → `agent-judges review --resume` → 循环至 done；终态产物落在 `.harness/evidence/judges/<run_id>/`（`verdict.json` + `report.md`），全程审计文件在 `.harness/logs/judges/<run_id>/`（`tasks/` + `results/` + `state.json`）。

### 手动 · CI/裸机回退（`--llm litellm`，需 API key）

```bash
python scripts/e2e_review.py                                        # 两个项目 × spec/plan
python scripts/e2e_review.py --project graphify-gitnexus --target spec --profile thorough
python scripts/e2e_review.py --llm mock                             # 零 token 冒烟
```

自动模式覆盖的场景：干净通过（Gate 1 早停 / 长内容 standard）与 critical 发现（Gate 2 thorough：2 轮辩论 + 盲评 + 元审查校准 + 人工升级），外加 `--llm litellm` 直连路径。手动模式适合人工评估检视质量：`report.md` 含全部 findings（severity/证据/建议），`verdict.json` 含可审计的 route 与置信度链。

## 架构

```
CLI (agent-judges review / list-reviewers / list-skills / evaluate)
  └─ 三层决策: 细粒度参数 > --profile > auto 路由(L1, 一次轻量 LLM 分类)
      └─ DebateOrchestrator (4 阶段, L0 确定性规则)
          ├─ Phase 1: 独立评审(并行 ThreadPoolExecutor, 超长输入 token 截断保护)
          ├─ Phase 2: 对抗辩论(≥2 reviewer 才开,每轮前查预算)
          ├─ Phase 3: 盲评终判(并行;单 reviewer 快检形态跳过)
          └─ Phase 4: 裁决合成(Severity.rank 最严 + 加权置信度)
              ├─ ReviewerRegistry   (MD 视角模板 → 匿名槽位)
              ├─ SkillRegistry      (SKILL.md 知识包: 模板引用 / skill: 即席加载)
              ├─ LLMBroker          (多模型管理 + 缓存 + 预算控制)
              ├─ EscalationRouter   (置信度 < 阈值 → 人工升级)
              └─ MetaReviewer       (可选,复用主链路 + 显式校准公式)
```

verdict 解析降级链：`complete_json`（litellm tool-use → response_format → prompt 注入 + JSON 正则，严格 schema 校验）→ `<SATISFIED>` 标签降级（AaaJ 原方案，同响应零额外调用，confidence 封顶 0.5）。

设计文档：[docs/spec.md](docs/spec.md) · [docs/design.md](docs/design.md) · [docs/plan.md](docs/plan.md)
