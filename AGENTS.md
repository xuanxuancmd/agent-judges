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
- 交付物：`integrations/<host>/agent/judge-manager.md` 驱动定义 + `agent-judges install`。

### 1.2 编排权归属：引擎状态机，禁止宿主 LLM 编排

- 编排（渐进式门控、4 阶段辩论、verdict 合成、解析降级、升级路由）必须留在引擎的
  **prepare/resume 状态机**（确定性代码，spec FR-11）——这是本项目立项根基
  （spec.md 1.1：单 agent 不可靠）。
- judge-manager 只做机械执行：逐字使用引擎生成的 prompt、原生拉起 reviewer Agent、
  原始输出落盘、调用引擎推进、终态汇报。**禁止改写 prompt / 自行增删任务 / 代答门控**。

### 1.3 LLM 能力宿主化：全部经实体 Agent，零 headless

- 主流场景下全部 LLM 能力（模型/凭证/额度）来自宿主已配置环境：每次 reviewer 调用 =
  宿主内拉起一个实体 reviewer Agent。用户零模型配置、零 API key。
- **主路径不得引入宿主专有的 headless CLI 调用**（`claude -p` / `opencode run` 等）——
  各家旗标差异是迁移任意工具的阻碍（NFR-7）。宿主依赖仅限三项公共能力：
  Agent 定义文件 / 原生 subagent 拉起 / shell。
- litellm 直连保留为 `--llm litellm`（CI/裸机回退），非主路径。

### 1.4 reviewer 模型配置：Agent 定义 frontmatter（宿主命名空间）

- `reviewers/*.md` 源与安装生成的宿主 Agent 定义中，`model` 写宿主命名空间：
  claude 系仅 Anthropic 模型（`opus`/`sonnet`/完整 ID）；opencode 系为 `provider/model`
  （已配置任意 provider，含自定义网关）。**省略 = 宿主默认模型**。
- **异构面板**（不同角色不同模型形成对抗）必须保留。已知边界：跨厂商混编需 opencode 宿主。

### 1.5 CLI 命名与安装

- 命令全称 **`agent-judges`**（废弃 `aj`，避免短名冲突）。
- `agent-judges install [--host auto|claude-code|opencode] [--global|--project]`：
  安装 judge-manager + 全部 reviewer Agent（含 meta-reviewer）；安装产物是**编译产物**，
  `reviewers/*.md` 与 `integrations/` 是唯一真相，改源后重装生效。

### 1.6 文档同步义务

- 改动 1.1–1.5 相关行为时，同步更新 spec.md（FR-2/3/5/6/10/11、NFR-7）、design.md、
  README。文档与行为不一致视为缺陷。

> **现状标注**（v2 已落地，2026-09-11）：`agent-judges` 命名、`install`、
> prepare/resume 状态机（`run_state.py`/`engine.py`）、reviewers MD 化、
> judge-manager 驱动定义（`integrations/{claude-code,opencode}/agent/`）
> 均已实施并有测试覆盖（端到端含早停/thorough+元审查两场景）。
> 遗留：`debate.py` 直连路径尚未重构为复用 `engine.advance`（双实现并存，
> 行为一致；重构属技术债）；design.md v2 增补章节未写。

---

## 2. 架构速览（改动前先读）

```
入口层  judge-manager Agent(宿主内,机械执行驱动协议)               [integrations/]
引擎层  agent-judges CLI: prepare/resume 状态机(门控/辩论/合成/升级)  [src/adversarial_judge/]
LLM层   宿主实体 reviewer Agent(模型=宿主配置) | litellm 直连(仅CI)   [src/adversarial_judge/llm/]
```

关键模块：

| 模块 | 职责 |
|---|---|
| `run_state.py` / `engine.py`（待建） | prepare/resume 状态机：`advance(state, results)` 纯函数推进（FR-11） |
| `debate.py` | 现行编排路径（litellm 直连保留；agent 模式重构为复用同一 advance 核心） |
| `progressive.py` | 两道纯规则门（早停 / 续跑强度）+ ProgressiveDecision 审计记录 |
| `router.py` | 确定性 reviewer 选择（文件名/内容提示 → 模板）+ PROFILE_MAP 三档 |
| `reviewer.py` / `skill.py` | reviewer 定义加载（MD frontmatter + persona 正文）/ SKILL.md 知识包 |
| `judge.py` / `llm/structured_output.py` | verdict 解析降级链（JSON 块 → 裸 JSON → `<SATISFIED>` 标签） |
| `consensus.py` | Phase 4 加权合成（Severity.rank 最严）+ consensus/stability |
| `meta_review.py` | 元审查（≥2 个 meta-reviewer 对抗）+ 显式校准公式 |
| `escalation.py` | 置信度（校准值优先）< 阈值 → `escalate_to_human` |

reviewer 约束模型（design.md 1.6）：用户模板只注入视角（persona + checklist），
辩论行为 / 输出格式 / 流程编排由系统固定（安装时审查框架并入 Agent 正文）。

## 3. 开发命令

```bash
python -m pytest tests/ -m "not integration" -q        # 单元测试（MockLLM，零 token）
python -m pytest tests/test_integration.py -m integration -v   # 需真实凭证
python -m mypy src/adversarial_judge                   # 类型检查（yaml stub 缺失为已知环境问题）
python -m adversarial_judge.cli list-reviewers         # CLI 调试（更名落地前）
```

## 4. 代码约定

- 类型安全：禁止类型抑制；边界输入一律 Pydantic 校验（parse, don't validate 业务层）
- 测试一律用 `tests/fixtures/mock_llm.py`（MockLLM / MockLLMBroker），单元测试零真实 API
- 门控 / 路由 / 合成等流程规则必须是纯函数（可表驱动测试）；LLM 不得决定流程主体
- 新增 reviewer 模板放 `reviewers/*.md`（MD 格式，见 spec FR-6），知识包放 `skills/`，均无需改代码
