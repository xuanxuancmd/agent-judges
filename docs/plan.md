# 对抗审查系统实施计划 (Plan)

> **文档状态**: 已实施(2026-09-11 落地;遗留项见 §7 风险表末行)
> **版本**: 2.0(宿主 Agent 化改造;取代 v0.1 初始构建计划——v0.1 已全部完成,存于 git 历史)
> **日期**: 2026-09-11
> **关联文档**: [spec.md](./spec.md)(v2,已同步刷新) · [design.md](./design.md)(v1 历史设计) · [AGENTS.md](../AGENTS.md) §1(需求约束)
> **前置条件**: 已读 AGENTS.md §1 需求约束与 spec.md v2

---

## 0. 背景与决策

### 0.1 改造目标(一句话)

把系统从"独立 CLI + litellm 直连"改造为"宿主 Agent 生态成员":入口是宿主内的
`judge-manager` 实体 Agent,reviewer 全部为宿主实体 Agent,LLM 能力(模型/凭证/额度)
全部来自宿主已有配置——用户零模型配置,且**主路径不依赖任何宿主专有的 headless CLI**。

### 0.2 已确认的架构决策

| # | 决策 | 内容 |
|---|---|---|
| D1 | 入口 | `judge-manager` 实体主 Agent(装入宿主);**不安装 skill**(意图匹配由 judge-manager 的 description 完成) |
| D2 | reviewer | 全部为宿主实体 Agent(从 `reviewers/*.md` 源生成安装);取消匿名 prompt 注入模式 |
| D3 | 执行模型 | 引擎以 **prepare/resume 状态机**编排:发出任务清单 → driver 机械执行 → 引擎确定性推进;门控/合成/降级全在引擎 |
| D4 | LLM 能力 | 主路径全部经宿主实体 Agent;litellm 直连保留为 `--llm litellm`(CI/裸机);主路径零 headless 依赖 |
| D5 | CLI 命名 | 命令全称 `agent-judges`(废弃 `aj`,避免短名冲突);`install` 为子命令 |
| D6 | 源格式 | `reviewers/*.yaml` → `*.md`(frontmatter=编排元数据+模型,正文=persona);`skills/` 知识包保持不变 |

### 0.3 迁移性论证(NFR-7 的依据)

主路径对宿主的依赖收敛为三项**公共能力**,均为当前主流 agent 工具的交集:

| 公共能力 | Claude Code | OpenCode | 新工具适配动作 |
|---|---|---|---|
| Agent 定义文件(MD+frontmatter) | `.claude/agents/*.md` | `.opencode/agent/*.md` | install 适配器加一个目标格式 |
| 原生 subagent 拉起 | Task tool | agent 调用 | 新写一份 judge-manager 驱动定义 |
| shell | bash tool | bash tool | 无 |

新增宿主 = 1 份驱动 MD + 1 个 install 适配;引擎与 reviewer 源**零改动**。
被移除的耦合:headless CLI(`claude -p`/`opencode run` 的旗标差异是各家工具分歧最大的部分)。

---

## 1. 实施计划总览

```
Phase 1: CLI 更名 + reviewer 源 MD 化              (基础清理, ~0.5-1 天)
Phase 2: 编排核心纯化 + prepare/resume 状态机        (核心, ~2-3 天)
Phase 3: agent-judges install                       (~1 天)
Phase 4: judge-manager 驱动定义(两宿主)             (~1 天)
Phase 5: 测试收口 + 文档同步                        (~1-1.5 天)

总计: ~6-8 天
依赖: Phase 1 → Phase 2 → (Phase 3, Phase 4 可并行) → Phase 5
```

---

## 2. Phase 1: CLI 更名 + reviewer 源 MD 化

**目标**: 命令切换到全称;reviewer 定义切换到 MD 格式(与 skills/ 同族),为 install 生成铺路。

| 任务 | 文件 | 内容 |
|---|---|---|
| 1-1 | `pyproject.toml` | script:移除 `aj`,注册 `agent-judges = "adversarial_judge.cli:app"` |
| 1-2 | `reviewers/*.md`(20 个) | YAML→MD 机械迁移:frontmatter(name/description/model/weight/majority_vote/skills)+ 正文(persona = 原 system_prompt)。**迁移时移除 model 字段值**(= 宿主默认;存量 litellm 串在宿主命名空间下无意义),文件内注释说明可选宿主命名空间模型写法 |
| 1-3 | `src/.../reviewer.py` | MD 解析(复用 skill.py 的 frontmatter 解析模式);Registry 同时兼容 `*.md`(优先)与 `*.yaml`(过渡期) |
| 1-4 | `tests/test_reviewer.py` 等 | MD 解析与迁移回归用例 |
| 1-5 | README / AGENTS.md / docs 命令示例 | `aj` → `agent-judges` |

**验收**:
- [ ] `agent-judges list-reviewers` 列出 20 个模板;`aj` 不再注册
- [ ] `agent-judges inspect-reviewer design-reviewer` 显示 persona 正文
- [ ] pytest 全绿,mypy 无新错误
- [ ] 仓库内无命令语境的 `aj ` 残留

---

## 3. Phase 2: 编排核心纯化 + prepare/resume 状态机

**目标**: 把渐进式门控 + 4 阶段流程重构为纯函数状态机,配双执行器;agent 驱动成为主路径。

### 3.1 编排核心(纯函数)

| 任务 | 文件 | 内容 |
|---|---|---|
| 2-1 | `src/.../run_state.py`(新) | `RunState` Pydantic 模型(阶段/面板/已收集 verdicts/门控记录/任务索引)+ run-dir 布局常量 |
| 2-2 | `src/.../engine.py`(新) | `advance(state, results) → (new_state, new_tasks | final)` 纯函数:复用 progressive 门、consensus 合成、judge 解析、prompts 构建器——**只重组调用边界,不改判定逻辑** |

状态机阶段(复用现有渐进式语义,判定逻辑零改动):

```
init → emit(phase-1: 哨兵 | 长内容全面板)
awaiting_sentinel → gate1 → 早停(final) | 面板扩张 → emit(panel)
awaiting_panel → gate2 → tier(standard | thorough)
  → emit(debate round 1..N) → awaiting_debate(逐轮推进)
  → emit(blind_final) → awaiting_final
  → synthesize → thorough? emit(meta tasks) → awaiting_meta → calibrate → final
```

### 3.2 双执行器

| 执行器 | 文件 | 机制 |
|---|---|---|
| **AgentTask(主路径)** | `cli/review.py` 扩展 | `--file X --run-dir RUN` 初始化、发出首批任务后退出;`--resume --run-dir RUN` 读 `results/*.md` → advance → 写新 tasks 或产出终态。任务 = `{task_id, agent, kind, prompt_file}`,prompt 逐字落盘 |
| **InProcess(CI)** | 现有 `debate.py` | `--llm litellm` 走进程内执行;**重构为调用同一 advance 核心**,消除双实现漂移 |

### 3.3 run-dir 布局(spec FR-11)

```
RUN/                        默认 .agent-judges/runs/<时间戳-slug>/
  state.json                状态机状态(幂等依据)
  input/content.md          被审查内容快照(+ context.md 可选)
  tasks/<id>.json + .md     待执行任务清单 + 逐字 prompt
  results/<id>.md           driver 写回的 Agent 原始输出
  verdict.json / report.md  终态产物
```

**验收**:
- [ ] 假 results 文件驱动状态机全路径单测(早停 / standard / thorough / 单 reviewer 池 / 长内容起跑),零 LLM
- [ ] `--resume` 幂等:同状态重复执行结果一致;中断后续跑正确
- [ ] `--llm litellm` 路径行为与现网一致(回归)
- [ ] `majority_vote > 1` 在 agent 模式 = 同 prompt 多任务并行,投票聚合在 advance 内完成
- [ ] 元审查(depth ≤ 2)任务发出与校准公式正确

---

## 4. Phase 3: agent-judges install

| 任务 | 文件 | 内容 |
|---|---|---|
| 3-1 | `cli/install.py`(新) | `install [--host auto\|claude-code\|opencode] [--global\|--project] [--reviewers-dir DIR]` |
| 3-2 | 宿主探测 | 按已存在目录(`~/.claude` / `~/.config/opencode`)auto 判定 |
| 3-3 | reviewer 生成器 | 源 MD → 宿主 agent MD:保留 name / model(宿主命名空间)/ description(前置"内部审查组件,由 judge-manager 经引擎编排调用,请勿直接触发")/ body(persona 正文 + `prompts.judge_system` 的系统固定审查框架);剥离 checklist/weight/majority_vote/skills 等引擎专有键;opencode 侧加 `mode: subagent` |
| 3-4 | judge-manager 安装 | 从 `integrations/<host>/agent/judge-manager.md` 模板安装(claude: 全局 agents 目录;opencode: agent 目录) |
| 3-5 | 幂等 | 重复 install 覆盖并提示;输出安装清单 |

**验收**:
- [ ] 临时目录伪宿主,golden-file 断言生成的 agent MD(防触发 description / 审查框架注入 / 引擎键剥离)
- [ ] `--project` 装项目级目录正确
- [ ] 源 MD 修改后重装生效(编译产物语义)

---

## 5. Phase 4: judge-manager 驱动定义

| 任务 | 文件 | 内容 |
|---|---|---|
| 4-1 | `integrations/claude-code/agent/judge-manager.md` | 驱动协议(见下)+ claude 侧实现指引(Task 并行拉起) |
| 4-2 | `integrations/opencode/agent/judge-manager.md` | 同协议的 opencode 版(原生 agent 拉起) |

**驱动协议**(两份共享的正文骨架):

```
1. bash: agent-judges review --file <目标> --run-dir RUN    (初始化,读输出任务清单)
2. 对每个任务: 原生拉起 tasks/<id>.json 指名的 Agent,
   prompt = tasks/<id>.md 内容【逐字使用,禁止改写/增删】
   Agent 最终回复原样写入 results/<id>.md
3. bash: agent-judges review --resume --run-dir RUN
4. 重复 2-3 直至 verdict.json 出现
5. 汇报: findings(severity/evidence/suggestion) + escalate_to_human + route 路径审计

红线: 不自行编排辩论;不改写 prompt;不跳过或代答门控;失败任务如实留空由引擎判定
```

judge-manager 的 description 写审查意图关键词(供宿主自动委派);opencode 侧可同时注册为主模式(用户直选)。

**验收**:
- [ ] 真实宿主冒烟:任选 claude-code 或 opencode,安装后对 `docs/spec.md` 跑通一次完整审查(渐进式路径)

---

## 6. Phase 5: 测试收口 + 文档同步

| 任务 | 内容 |
|---|---|
| 5-1 | 集成测试:伪 driver(脚本模拟 judge-manager 行为)驱动 run-dir 全流程 |
| 5-2 | README 重写:宿主用法为首章(install → 对话式审查),CLI 参考为附录;移除 headless/凭证继承章节中已被取代的内容 |
| 5-3 | design.md:追加 v2 增补章节(执行模型 / install),标注 1.5/4.2/4.8 中被替代的范围 |
| 5-4 | spec.md / AGENTS.md 收口复核(本轮已刷新) |

**验收**:
- [ ] pytest 全绿(单测零真实 LLM;真实宿主冒烟独立标记)
- [ ] spec.md / design.md / AGENTS.md / README 与行为一致(AGENTS.md §1.6 同步义务)

---

## 7. 风险与回退

| 风险 | 缓解 |
|---|---|
| driver LLM 执行走样(改 prompt/漏落盘) | 协议红线写死 + prompt 逐字落盘 + resume 幂等可重放;advance 前校验 results 完整性,缺失任务不推进 |
| 宿主 agent 拉起无并行能力 | 顺序执行仍正确(仅慢);协议不假设并行 |
| 双执行器漂移 | InProcess 重构为复用同一 advance 核心 |
| claude 宿主需要非 Anthropic 模型 | 已知边界(spec FR-3);跨厂商混编面板用 opencode 宿主 |
| 回退 | `--llm litellm` 全程保留 = 完整回退路径;Phase 1 独立可回退(git revert) |
