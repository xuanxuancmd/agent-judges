[deployment-config-reviewer 审查回复]

被审查内容是一份功能规格说明书（spec.md），而非部署配置文件（无 Dockerfile / K8s manifests / Terraform / CI 配置）。检查清单中关于非 root 运行、具体版本标签、健康检查、资源限制、优雅停机等部署专项条目无法直接评估——内容中根本不包含这些部署制品。但作为 DevOps/平台工程审查者，审查了 spec 中与配置一致性、可运维性、可复现性相关的方面。

主要发现：(1) spec 定义了包含服务端组件（MCP stdio server）和外部服务集成（Neo4j/FalkorDB/Gemini/嵌入后端）的系统，但 NFR 章节未覆盖可运维性需求；(2) 多个外部服务依赖需要凭证，但 spec 未定义任何配置接口，也未提出 secret 管理要求，存在配置漂移与凭证硬编码风险；(3) BM25 倒排索引作为新增侧车制品未指定存储路径。所有发现均为 minor，因为 spec 是功能规格而非部署配置，部署专项缺失属于范畴边界问题而非配置错误。

```json
{
  "severity": "minor",
  "confidence": 0.7,
  "reasoning": "被审查内容是一份功能规格说明书（spec.md），而非部署配置文件（无 Dockerfile / K8s manifests / Terraform / CI 配置）。因此，检查清单中关于非 root 运行、具体版本标签、健康检查、资源限制、优雅停机等部署专项条目无法直接评估——内容中根本不包含这些部署制品。但作为 DevOps/平台工程审查者，我审查了 spec 中与配置一致性、可运维性、可复现性相关的方面，发现以下问题：(1) spec 定义了包含服务端组件（MCP stdio server）和外部服务集成（Neo4j/FalkorDB/Gemini/嵌入后端）的系统，但 NFR 章节未覆盖可运维性需求（健康检查、资源限制、日志策略、优雅停机）；(2) 多个外部服务依赖需要凭证，但 spec 未定义任何配置接口（环境变量/配置文件/连接参数/端口），也未提出 secret 管理要求，存在配置漂移与凭证硬编码风险；(3) BM25 倒排索引作为新增侧车制品，与所有现有制品（均有明确路径）不同，未指定存储路径，存在配置一致性缺口。所有发现均为 minor，因为 spec 是功能规格而非部署配置，部署专项缺失属于范畴边界问题而非配置错误。",
  "findings": [
    {
      "description": "服务端组件与外部服务集成缺少可运维性需求。spec 定义了 MCP stdio server（FR-6 扩展其工具集）以及 Neo4j/FalkorDB 直接推送能力，但 NFR-1 至 NFR-6 仅覆盖索引性能、增量更新耗时、存储占用、向后兼容、确定性、诚实性，未包含任何可运维性需求（健康检查/就绪探针、资源限制、日志输出到 stdout/收集管道、优雅停机处理）。对于包含长期运行服务端组件的系统，这是规格层面的可运维性缺口。",
      "severity": "minor",
      "confidence": 0.75,
      "evidence": "第 2.5 节：'MCP 服务：--mcp 启动 stdio MCP server，供 agent 查询'；FR-6：'在现有 --mcp 的 query/path/explain 基础上，补齐代码分析专用工具'；第 2.5 节：'--neo4j / --falkordb 生成 Cypher 脚本或直接推送'；NFR-1 至 NFR-6（第 6 节）均未涉及健康检查、资源限制、日志策略或优雅停机。",
      "suggestion": "在 NFR 章节新增可运维性需求：MCP server 应定义健康检查端点或信号、资源限制（CPU/内存上限）、日志输出到 stdout 的约定、以及收到终止信号时的优雅停机处理（flush 缓存、关闭连接）。"
    },
    {
      "description": "外部服务的配置接口与 secret 管理未定义。spec 引用了多个需要配置和凭证的外部服务：Neo4j/FalkorDB（直接推送需连接参数与凭证）、Gemini LLM 后端（需 API key）、嵌入后端如 sentence-transformers（需配置）。但 spec 未定义任何配置接口（环境变量名、配置文件路径、连接参数、端口），也未提出 secret 管理要求。这构成配置漂移风险——无法验证基础设施提供的配置项与代码读取的配置项一致——以及凭证硬编码风险。",
      "severity": "minor",
      "confidence": 0.7,
      "evidence": "第 2.5 节：'--neo4j / --falkordb 生成 Cypher 脚本或直接推送'（直接推送需要连接配置与凭证）；第 2.1 节：'支持 Gemini 后端（可选）'（需 API key）；第 2.5 节：'build_embeddings 生成向量索引侧车（配置后端时）'；第 3.2 节：'build_embeddings（配置后端，如 sentence-transformers）'；spec 全文未定义配置文件 schema、环境变量命名、或 secret 管理要求。",
      "suggestion": "新增配置规格章节，声明各外部后端的配置接口（环境变量/配置文件/CLI 参数）、凭证应通过 secret 管理而非硬编码、以及配置项与代码读取项的一致性校验机制。"
    },
    {
      "description": "BM25 倒排索引制品路径未指定。spec 为所有现有制品明确定义了存储路径（.graph/graph.json、.graph/.graphify_ast.json、.graph/cost.json、.graph/GRAPH_REPORT.md、.graph/.graphify_analysis.json），但 FR-7 和 NFR-3 引入的新增 BM25 倒排索引侧车文件未指定路径。在配置一致性方面，这是已有明确路径约定体系中的缺口。",
      "severity": "minor",
      "confidence": 0.6,
      "evidence": "第 2.4 节明确列出所有现有制品路径：'.graph/graph.json（JSON 文件），附带 .graph/GRAPH_REPORT.md 审计报告和 .graph/.graphify_analysis.json 分析侧车'；第 2.1 节：'提取结果写入 .graph/.graphify_ast.json'；第 2.6 节：'每轮运行的 token 消耗记录在 .graph/cost.json'；FR-7：'构建 BM25 倒排索引（覆盖符号名、限定名、文件路径、文档注释）'（无路径）；NFR-3：'BM25 倒排索引作为独立侧车文件存储，不膨胀主 graph.json'（无路径）。",
      "suggestion": "在 FR-7 或 NFR-3 中明确 BM25 倒排索引的存储路径（如 .graph/.graphify_bm25.json），与现有制品路径约定保持一致。"
    },
    {
      "description": "依赖版本锁定要求未显式声明。NFR-5 要求'AST 提取与 Resolution 阶段必须完全确定性（相同输入产生相同输出）'，FR-1 声明'不引入新语言依赖'，但 spec 未显式要求对 Tree-sitter 解析器及语言特定 resolver 进行版本锁定。确定性输出隐含依赖版本锁定，但未作为独立可验证需求提出，影响构建可复现性。",
      "severity": "minor",
      "confidence": 0.5,
      "evidence": "NFR-5：'AST 提取与 Resolution 阶段必须完全确定性（相同输入产生相同输出），不依赖 LLM'；FR-1：'语言支持至少达到：TypeScript、JavaScript、Python、Go、Java、Rust（与 graphify 现有支持对齐，不引入新语言依赖）'；spec 未提及依赖版本锁定、锁文件或可复现构建要求。",
      "suggestion": "在 NFR-5 或新增 NFR 中显式要求：Tree-sitter 及各语言 resolver 依赖应锁定版本（如 lockfile），确保不同环境下构建结果可复现。"
    }
  ],
  "satisfied": false
}
```
