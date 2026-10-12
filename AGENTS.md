# AGENTS.md — adversarial-judge (agent-judges)

面向在本仓库工作的编码 agent（Claude Code / OpenCode 等）。**第 1 节是产品级需求约束，
任何设计决策与代码改动不得违反**；其余为开发指南。

---

## 1. 需求约束（最高优先级）

### 1.1 入口形态：judge-manager 实体 Agent；不安装 skill

- **主流场景**：用户在宿主 agent 会话中提出审查诉求（"审查/审阅/审计这份 spec"），
  由宿主委派/用户直呼 `judge-manager` 实体 Agent（安装于宿主）完成审查。
  意图匹配靠 judge-manager 的 description，**不引入宿主 skill**。
- `agent-judges` CLI 是**引擎 + 安装器**，由 judge-manager 通过 shell 调用；
  直接命令行使用仅服务于开发者调试与 CI。
- 交付物：`integrations/<platform>/agent/judge-manager.md` + `reviewer.md` 驱动定义 + `agent-judges install`。
- 安装时只装 2 个 Agent：`judge-manager`（对外入口）+ `reviewer`（匿名审查槽位，无 persona）；
  reviewer 的 persona 由引擎在发出任务时编译进 task prompt，judge-manager 逐字传给匿名 reviewer 执行。

### 1.2 编排权归属：引擎状态机，禁止宿主 LLM 编排

- 编排（渐进式门控、4 阶段辩论、verdict 合成、解析降级、升级路由）必须留在引擎的
  **prepare/resume 状态机**（确定性代码，spec FR-11）——这是本项目立项根基
  （spec.md 1.1：单 agent 不可靠）。
- judge-manager 只做机械执行：逐字使用引擎生成的 prompt（含 reviewer persona）、原生拉起匿名 reviewer Agent、
  原始输出落盘、调用引擎推进、终态汇报。**禁止改写 prompt / 自行增删任务 / 代答门控**。

### 1.3 LLM 能力宿主化与模型配置

- 全部 LLM 能力来自宿主已配置环境：每次 reviewer 调用 = 宿主内拉起一个匿名 reviewer Agent。用户零模型配置、零 API key。
- reviewer 的 persona + 系统固定审查框架由引擎在发出任务时编译进 task prompt，judge-manager 逐字传给匿名 reviewer 执行。
- **主路径不得引入宿主专有的 headless CLI 调用**（`claude -p` / `opencode run` 等）——
  各家旗标差异是迁移任意工具的阻碍（NFR-7）。宿主依赖仅限三项公共能力：
  Agent 定义文件 / 原生 subagent 拉起 / shell。
- `reviewers/*.md` 中 `model` 字段写宿主命名空间：
  claude 系仅 Anthropic 模型（`opus`/`sonnet`/完整 ID）；opencode 系为 `provider/model`。**省略 = 宿主默认模型**。
- litellm 直连（`--llm litellm`）降级为内部测试设施，仅供 CI / 开发者调试，不在面向用户的文档中体现。

### 1.4 CLI 命名与安装

- 命令全称 **`agent-judges`**。
- `agent-judges install [--platform codeagent|claude-code|opencode|auto] [--project]`：
  安装 judge-manager + 匿名 reviewer Agent（仅 2 个）；安装产物是**编译产物**，
  `integrations/<platform>/agent/` 是唯一真相，改模板后重装生效。
- 默认平台 `codeagent`（claude 兼容机制，目录 `.cac`）。

### 1.5 主路径：宿主 Agent 驱动

项目的唯一主路径是宿主 Agent 驱动模式——LLM 能力通过宿主内的 reviewer Agent 访问，CLI 不直接调用 LLM。后续开发以此为核心：

- **强化 agent 模式能力**：prepare/resume 状态机已落地（`engine.py`），继续完善 driver 协议的健壮性（断点续跑、失败重试、超时处理）
- **消除双实现**：`debate.py` 的 litellm 直连路径与 `engine.py` 的 `advance` 核心并存是技术债。后续将 `debate.py` 重构为复用 `engine.advance`，消除双实现维护负担
- **litellm 直连降级为内部测试设施**：`--llm litellm` 仅保留给 CI 和开发者调试，不在面向用户的文档中体现，不作为产品路径维护

### 1.6 文档同步义务

- 改动 1.1–1.4 相关行为时，同步更新 spec.md（FR-2/3/5/6/10/11、NFR-7）、design.md、
  README。文档与行为不一致视为缺陷。

---

## 2. 架构速览（改动前先读）

```
入口层  judge-manager Agent(宿主内,机械执行驱动协议)               [integrations/]
引擎层  agent-judges CLI: prepare/resume 状态机(门控/辩论/合成/升级)  [src/adversarial_judge/]
LLM层   宿主实体 reviewer Agent(模型=宿主配置)                      [src/adversarial_judge/llm/]
        (litellm 直连为内部测试设施,见 5.1)
```

关键模块：

| 模块 | 职责 |
|---|---|
| `run_state.py` / `engine.py` | prepare/resume 状态机：`advance(state, results)` 纯函数推进（FR-11） |
| `debate.py` | 4 阶段辩论编排（litellm 直连路径，技术债：待重构为复用 `engine.advance`，见 5.1） |
| `progressive.py` | 两道纯规则门（早停 / 续跑强度）+ ProgressiveDecision 审计记录 |
| `router.py` | 确定性 reviewer 选择（文件名/内容提示 → 模板）+ PROFILE_MAP 三档 |
| `reviewer.py` / `skill.py` | reviewer 定义加载（MD frontmatter + persona 正文）/ SKILL.md 知识包 |
| `judge.py` / `llm/structured_output.py` | verdict 解析降级链（JSON 块 → 裸 JSON → `<SATISFIED>` 标签） |
| `consensus.py` | Phase 4 加权合成（Severity.rank 最严）+ consensus/stability |
| `meta_review.py` | 元审查（≥2 个 meta-reviewer 对抗）+ 显式校准公式 |
| `escalation.py` | 置信度（校准值优先）< 阈值 → `escalate_to_human` |

## 3. 开发命令

```bash
python -m pytest tests/ -m "not integration" -q        # 单元测试（MockLLM，零 token）
python -m pytest tests/test_integration.py -m integration -v   # 需真实凭证
python -m mypy src/adversarial_judge                   # 类型检查（yaml stub 缺失为已知环境问题）
python -m adversarial_judge.cli list-reviewers         # 列出内置视角模板
```

## 4. 代码约定

- 类型安全：禁止类型抑制；边界输入一律 Pydantic 校验（parse, don't validate 业务层）
- 测试一律用 `tests/fixtures/mock_llm.py`（MockLLM / MockLLMBroker），单元测试零真实 API
- 门控 / 路由 / 合成等流程规则必须是纯函数（可表驱动测试）；LLM 不得决定流程主体
- 新增 reviewer 模板放 `reviewers/*.md`（MD 格式，见 spec FR-6），知识包放 `skills/`，均无需改代码

---
