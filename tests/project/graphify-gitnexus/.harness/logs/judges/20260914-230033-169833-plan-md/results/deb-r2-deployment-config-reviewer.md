[deployment-config-reviewer R2 辩论 - plan.md]

向 design-reviewer 让步 CI 工具链一条。维持 4 项 major：测试仓库来源与 CI 可复现性、sidecar 一致性与原子写入、--update 崩溃恢复、MCP 工具运行时资源限制。支持 SR-1/SR-2/SR-3 和 DR-2/DR-3。

```json
{
  "satisfied": false,
  "findings": [
    {
      "id": "DCR-1",
      "severity": "major",
      "confidence": 0.80,
      "title": "测试仓库来源与 CI 可复现性缺失",
      "evidence": "T0.1/T5.1 选定测试仓库但未说明来源、许可证、CI 获取策略。CI 在不同环境不可复现。",
      "suggestion": "T0.1 增加交付物：测试仓库清单（repo URL + commit pin）+ fixture 固化策略。"
    },
    {
      "id": "DCR-2",
      "severity": "major",
      "confidence": 0.78,
      "title": "存储 sidecar 一致性与原子写入设计缺失",
      "evidence": "T3.9 创建 .graph/bm25_index.json 作为 sidecar，但未设计原子写入策略、与 graph.json 的一致性约束、stale sidecar 的检测与重建路径。",
      "suggestion": "T3.9 增加：sidecar 写入采用 temp-file + atomic rename；定义一致性版本号。"
    },
    {
      "id": "DCR-3",
      "severity": "major",
      "confidence": 0.72,
      "title": "--update 崩溃恢复与事务安全性未设计",
      "evidence": "T2.7/T2.8 manifest 记录符号级哈希但无回滚路径。--update 中途失败时 manifest 与 graph.json 的恢复未设计。",
      "suggestion": "T2.7/T2.8 增加：--update 采用 write-ahead 或 staging-area 模式，失败可回滚。"
    },
    {
      "id": "DCR-4",
      "severity": "major",
      "confidence": 0.70,
      "title": "MCP 工具运行时资源限制未定义",
      "evidence": "T3.5 注册四工具但仅 impact 设深度上限。trace/context/detect_changes 无 timeout/内存上限/并发策略。",
      "suggestion": "T3.5 为每个 MCP 工具定义 timeout、响应大小上限、并发上限。"
    },
    {
      "id": "DCR-5",
      "severity": "minor",
      "confidence": 0.85,
      "title": "向 design-reviewer 让步：撤回 CI 工具链发现",
      "evidence": "计划文档应声明 CI 策略（§8.4 已做到），工具链选择是实现期决策。",
      "suggestion": "无（让步）。"
    },
    {
      "id": "DCR-6",
      "severity": "minor",
      "confidence": 0.68,
      "title": "Tree-sitter 依赖可部署性（支持 DR-3）",
      "evidence": "Tree-sitter 原生二进制跨平台可用性需提前确认。",
      "suggestion": "支持 DR-3 的 T0.0 评估任务建议。"
    },
    {
      "id": "DCR-7",
      "severity": "minor",
      "confidence": 0.62,
      "title": "性能基准环境规格缺失",
      "evidence": "T5.1/T5.3 无硬件基线与运行环境定义。NFR-1/2 在不同硬件下不可比。",
      "suggestion": "T5.1 增加基准硬件配置和运行环境定义。"
    }
  ],
  "summary": "向 design-reviewer 让步 CI 工具链一条。维持 4 项 major：测试仓库来源与 CI 可复现性、sidecar 一致性与原子写入、--update 崩溃恢复、MCP 工具运行时资源限制。支持 SR-1/SR-2/SR-3 和 DR-2/DR-3。"
}
```
