# adversarial-judge (aj)

一个通用的、可外部定义 reviewer 与 skill 的、多 agent 辩论式的、置信度驱动人工升级的、且自身可递归审查的 AI 产出审计系统。

> 受 [Agent-as-a-Judge](https://arxiv.org/pdf/2410.10934) (ICML 2025) 启发的重写。MIT 许可。

## 这是什么

所有 AI 产出的东西（需求文档、规格、设计、代码、测试计划、检视报告…）都需要被另一个（组）AI **对抗审查**一遍——单 Agent 有幻觉、遗漏、过度自信等问题。本系统提供：

- **4 阶段辩论编排**：N 个 reviewer 独立评审（并行）→ 1-3 轮对抗辩论 → 盲评终判 → 裁决合成
- **YAML 视角模板 + SKILL.md 审查 skill**：审查者与知识包均通过外部文件定义，无需改代码
- **多模型混用**：不同 reviewer 可指定不同 LLM（Claude sonnet + opus + GPT-4o），避免同模型共享盲区
- **置信度 + 人工升级**：`confidence < 阈值 → escalate_to_human: true`
- **元审查**：审查结果本身可被再次审查，通过显式校准公式修正置信度
- **auto 路由**：零参数调用，一次轻量 LLM 分类自动选档位与 reviewer 组合

**不做什么**：代码风格、命名规范、设计模式、性能微优化（传统 code review 范畴）。但外部代码检视工具（SonarQube/ESLint/人工 review）的**产物**可以被本系统审查。

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

`aj` 是被编码 agent 通过 shell 调用的质量关卡，**LLM 凭证优先从调用方会话环境继承**，解析顺序：显式参数 > 环境变量 > litellm 内部回退（见 `llm/credentials.py`）。

### Claude Code

| 会话认证方式 | aj 能否复用 | 说明 |
|---|---|---|
| `ANTHROPIC_API_KEY`（API key 认证） | ✅ 自动继承 | 子进程继承环境变量 |
| `ANTHROPIC_AUTH_TOKEN`（网关/代理 Bearer） | ✅ 自动继承 | 同上 |
| `claude setup-token` 导出 `CLAUDE_CODE_OAUTH_TOKEN` | ✅ 自动继承 | litellm 识别 `sk-ant-oat*` 前缀并走 Bearer + OAuth beta 头 |
| Pro/Max 订阅登录（`/login`） | ❌ 不可复用 | OAuth 凭证存储在 `~/.claude/.credentials.json`，**不导出**到子进程环境；请改用 `claude setup-token` 或设置 `ANTHROPIC_API_KEY` |

> 注意：宿主设置 `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` 时，所有凭证会从子进程环境中剥离，`aj` 无法继承——此时需在 `.env` 显式配置或经本地网关（`--base-url`）访问。

```bash
# Claude Code 会话内（bash 工具直接调用，凭证从会话环境继承）:
aj review --file ./spec.md -r spec-reviewer -o json | jq .verdict.escalate_to_human
```

### OpenCode

OpenCode 的 provider 凭证存储在 `~/.local/share/opencode/auth.json`，**不会**导出为子进程环境变量；官方 `opencode serve` 是管理 API，不是 Anthropic/OpenAI 线协议代理。两种接法：

```bash
# 方式 1（推荐）: 安装社区插件 opencode-llm-proxy
# （本地 127.0.0.1:4010，Anthropic/OpenAI 线协议兼容，转发到 opencode 已配置的 provider）
aj review --file ./spec.md --base-url http://127.0.0.1:4010

# 方式 2: 在启动 opencode 的 shell 中显式 export provider key
# （环境具有传递性：opencode 进程环境中有，其 bash 子进程就能看到）
export ANTHROPIC_API_KEY="sk-ant-***"
```

### 解析顺序速查

- `anthropic/*` 模型：`--base-url`/显式参数 > `ANTHROPIC_API_KEY` > `ANTHROPIC_AUTH_TOKEN` > `CLAUDE_CODE_OAUTH_TOKEN` >（网关）`ANTHROPIC_BASE_URL`
- `openai/*` 模型：`OPENAI_API_KEY` / `OPENAI_BASE_URL`
- 无凭证时 CLI 给出可操作提示（本地模型如 `ollama/*` 不误报）；`meta-reviewer-2`（GPT-4o）需要 `OPENAI_API_KEY`，缺失时该 reviewer 按容错策略降级，不影响整体产出

## 快速开始

```bash
# 列出 20 个内置视角模板与 3 个内置 skill
aj list-reviewers
aj list-skills

# 零决策全自动(推荐): auto 路由自动判定档位 + reviewer 组合
aj review --file ./spec.md

# 半决策: 显式选档
aj review --file ./spec.md --profile fast      # 快检(1 次调用)
aj review --file ./spec.md --profile standard  # 常规审查(2 reviewer + 1 轮辩论)
aj review --file ./spec.md --profile thorough  # 深审(3 reviewer + 2 轮辩论 + 元审查)

# 全决策: 细粒度参数
aj review --content "我们的系统需要支持高并发..." \
  -r requirement-elicitation-reviewer \
  -r spec-reviewer \
  --debate-rounds 2 \
  --threshold 0.8

# 即席加载 skill 为审查视角(通用匿名 agent 加载用户自定义 skill)
aj review --file api-spec.md -r skill:api-contract-review
aj review --file gateway-config.md -r skill:owasp-top10 --debate-rounds 0

# 管道接入(Claude Code / OpenCode / CI)
cat requirements.md | aj review -r requirement-elicitation-reviewer -o json | jq '.verdict.escalate_to_human'

# 元审查: 审查上一轮的审查结果
aj review --file verdict.json --meta-review -o json > meta_verdict.json

# 双格式输出到目录
aj review --file ./spec.md -r spec-reviewer --output both --output-dir ./reports

# 预算控制 + 强制覆盖模型 + 本地网关(测试用)
aj review --file ./spec.md -r spec-reviewer --override-model openai/gpt-4o --max-cost 0.50
aj review --file ./spec.md -r spec-reviewer --base-url http://localhost:11434

# 低置信度时暂停等待人工裁决
aj review --file ./spec.md -r spec-reviewer --interactive

# 置信度校准评估(验证"高置信度判断是否确实更准确": Accuracy/AUROC)
aj evaluate --predictions verdicts.json --labels human_labels.json
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

复制 `reviewers/custom_example.yaml` 为新文件，修改后即可使用：

```yaml
name: my-security-auditor        # 唯一标识(slug)
description: 安全审计视角
# model: anthropic/claude-opus-4-20250514   # 可选,不指定用 --model 默认值
system_prompt: |                 # 审查者人设 + 关注维度
  你是一位安全审计专家……
checklist:                       # 检查清单
  - criteria: 认证与授权路径完整
skills:                          # 可选:引用审查 skill(知识注入)
  - owasp-top10
weight: 1.0                      # 聚合权重
majority_vote: 1                 # >1 时同模型多次调用投票(轻量级反幻觉)
```

```bash
aj review --file doc.md -r my-security-auditor
```

## 自定义审查 skill

skill 是**知识注入型**的用户自定义审查知识包（SKILL.md 格式，兼容业界 skill 约定；纯 LLM 范式——不含工具执行）。由通用匿名 agent 槽位加载，两种方式：

**方式 1：即席加载**（skill = 完整审查视角）：

```bash
aj review --file api-spec.md -r skill:api-contract-review
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
aj list-skills                        # 查看可用 skill
aj review --file x.md -r skill:my-compliance-skill --debate-rounds 0
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
| `custom_example.yaml` | 自定义模板示例（含字段说明） |

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

## 架构

```
CLI (aj review / list-reviewers / list-skills / evaluate)
  └─ 三层决策: 细粒度参数 > --profile > auto 路由(L1, 一次轻量 LLM 分类)
      └─ DebateOrchestrator (4 阶段, L0 确定性规则)
          ├─ Phase 1: 独立评审(并行 ThreadPoolExecutor, 超长输入 token 截断保护)
          ├─ Phase 2: 对抗辩论(≥2 reviewer 才开,每轮前查预算)
          ├─ Phase 3: 盲评终判(并行;单 reviewer 快检形态跳过)
          └─ Phase 4: 裁决合成(Severity.rank 最严 + 加权置信度)
              ├─ ReviewerRegistry   (YAML 视角模板 → 匿名槽位)
              ├─ SkillRegistry      (SKILL.md 知识包: 模板引用 / skill: 即席加载)
              ├─ LLMBroker          (多模型管理 + 缓存 + 预算控制)
              ├─ EscalationRouter   (置信度 < 阈值 → 人工升级)
              └─ MetaReviewer       (可选,复用主链路 + 显式校准公式)
```

verdict 解析降级链：`complete_json`（litellm tool-use → response_format → prompt 注入 + JSON 正则，严格 schema 校验）→ `<SATISFIED>` 标签降级（AaaJ 原方案，同响应零额外调用，confidence 封顶 0.5）。

设计文档：[docs/spec.md](docs/spec.md) · [docs/design.md](docs/design.md) · [docs/plan.md](docs/plan.md)
