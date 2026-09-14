# TODO 列表应用：执行计划

## 1. 技术选型

- 形态：单页前端应用，无后端服务。
- 存储：浏览器 localStorage，数据以 JSON 数组形式序列化。
- 框架：原生 JavaScript 加少量 DOM 操作，不引入前端框架，保持零依赖与体积小。
- 构建：直接静态文件（index.html、app.js、style.css），无需打包工具。
- 浏览器支持：Chrome、Edge、Firefox 的最近两个大版本。

选型理由：本应用数据量小、交互简单，引入框架反而增加体积与学习成本。原生方案足以覆盖需求，部署只需一个静态服务器或直接打开文件。

## 2. 里程碑划分

整体分四个里程碑，前后存在依赖，按顺序推进。

- M1 数据模型与存储
- M2 核心 CRUD 逻辑
- M3 界面与交互
- M4 测试与打磨

M1 为 M2 提供存储基础，M2 为 M3 提供可调用的纯逻辑，M3 完成后进入 M4 验证与打磨。

## 3. 阶段任务分解

### M1 数据模型与存储

任务：

- 定义事项数据结构：`{ id: string, title: string, dueDate: string|null, completed: boolean, createdAt: string }`。
- 封装 localStorage 读写：`loadTodos()` 返回数组，`saveTodos(todos)` 写入。
- ID 生成：采用时间戳加随机后缀，保证单设备下基本不冲突。
- 读取异常处理：localStorage 为空或 JSON 解析失败时返回空数组，不抛错。

数据示例：

```json
{
  "id": "1694200000000-a3f",
  "title": "整理周会纪要",
  "dueDate": "2026-09-20",
  "completed": false,
  "createdAt": "2026-09-14T10:00:00Z"
}
```

交付物：`storage.js`，导出 `loadTodos` 与 `saveTodos`。

### M2 核心 CRUD 逻辑

任务：

- 实现纯逻辑函数：`addTodo`、`updateTodo`、`removeTodo`、`getTodos`。
- 实现完成切换：`toggleCompleted(id)`。
- 实现筛选：`filterTodos(todos, view)`，view 取值 `all` / `active` / `completed`。
- 标题校验：新增与编辑时标题去空格后非空，空标题拒绝。
- 过期判定：提供 `isOverdue(todo)` 辅助函数，供界面调用。

交付物：`todoService.js`，全部为不操作 DOM 的纯函数，可独立测试。

### M3 界面与交互

任务：

- 搭建 HTML 骨架：顶部输入区（标题输入框、日期选择器、新增按钮），中部列表区，底部筛选切换。
- 渲染列表项：标题、截止日期、完成复选框、编辑入口、删除按钮。
- 绑定事件：新增、编辑提交、删除、切换完成、切换筛选。
- 编辑交互：点击编辑入口后将标题与日期转为可编辑输入，提交后调用 `updateTodo`。
- 过期提示：截止日期早于当天且未完成的事项，整行加红色左边框。
- 默认筛选视图为未完成。
- 每次数据变动后重新渲染列表并写回 localStorage。

交付物：`index.html` 与 `ui.js`，可在浏览器中直接运行的应用。

### M4 测试与打磨

任务：

- 为 `todoService` 与 `storage` 编写单元测试，覆盖 CRUD、筛选、空数据与异常解析。
- 逐条手工核对需求规格中的验收标准，记录通过与否。
- 走查交互细节，修复发现的问题。

交付物：单元测试脚本、验收核对记录、可发布版本。

## 4. 测试策略

- 单元测试：覆盖 CRUD、筛选、存储读写与异常分支，使用 Mock 的 localStorage，不依赖真实浏览器存储。
- 手工验收：按需求规格的验收标准逐条核对，重点关注数据持久化与筛选正确性。
- 编辑流程走查：逐项验证新增、编辑提交、删除、完成切换后的列表渲染与写回是否一致。
- 浏览器兼容性：在 Chrome、Edge、Firefox 各验证一次主流程。

## 5. 风险与应对

- localStorage 容量可能不足：数据量大时可能触发配额错误。
- 无框架导致 DOM 操作代码偏长：通过封装小的渲染辅助函数缓解。
- 浏览器兼容性差异：以特性检测兜底，遇不支持的 API 给出降级提示。

## 6. 交付物汇总

- `storage.js`：localStorage 读写封装。
- `todoService.js`：核心 CRUD 与筛选纯逻辑。
- `index.html` / `ui.js` / `style.css`：可运行的应用界面。
- 单元测试脚本与验收核对记录。

各里程碑结束时核对对应交付物，全部完成后整体走查一遍再定为可发布版本。
