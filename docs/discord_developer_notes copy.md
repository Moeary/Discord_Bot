# Discord 机器人开发实用文档（官方文档提炼）

来源：
- https://docs.discord.com/developers/intro
- Discord Developer Docs（OAuth2、Gateway Intents、Interactions、Permissions、Guild Member Moderation）

更新时间：2026-03-18

---

## 1. 本项目最相关的能力地图

你当前项目涉及：
- Slash 命令（`/ai`、`/fun`、`/config`）
- 消息事件（`on_message`）
- Reaction 事件（`on_raw_reaction_add`）
- 权限检查（管理员触发收税）
- 成员超时禁言（`member.timeout(...)`）

对应官方概念：
- **Interactions API**：Slash 命令
- **Gateway Events**：消息、reaction、成员更新
- **OAuth2 + Bot Permissions**：邀请和权限授予
- **Moderation APIs**：timeout/communication disabled until

---

## 2. OAuth2 邀请与权限（你截图相关）

### 2.1 推荐 OAuth2 Scopes
- `bot`
- `applications.commands`

这两个 scope 对你当前机器人是正确且必需的。

### 2.2 推荐 Bot Permissions（最小可用）
- `View Channels`
- `Send Messages`
- `Read Message History`
- `Add Reactions`
- `Embed Links`
- `Attach Files`
- `Use Slash Commands`
- `Moderate Members`（用于 timeout）

如果已经给了 `Administrator`，通常足够覆盖以上权限。

### 2.3 常见误区
- OAuth2 scope 选对了，但频道覆盖权限把 bot 拒绝了（仍会失效）。
- 机器人可发送消息，不代表可读取历史或处理 reaction。

---

## 3. Gateway Intents（事件能否收到的关键）

### 3.1 代码侧声明（discord.py）
你项目已声明：
- `guilds=True`
- `members=True`
- `message_content=True`
- `messages=True`
- `reactions=True`

### 3.2 开发者后台必须同步开启（重要）
在 Discord Developer Portal -> Bot 中：
- `MESSAGE CONTENT INTENT`（你要读消息文本，必须开）
- `SERVER MEMBERS INTENT`（成员相关功能常用）

若后台未开，即使代码写了 intent 也可能收不到关键数据。

---

## 4. Slash 命令（Interactions）

### 4.1 注册/同步
- 全局命令：传播慢（可能需要时间）
- 测试服命令（guild scoped）：同步快，适合开发

### 4.2 交互响应时序
- 3 秒内要 `respond` 或 `defer`
- 长耗时操作（如 AI 绘图）应 `defer` 后 followup

### 4.3 失败处理
- 对外只返回可读错误
- 真实异常写日志（HTTP code、payload 摘要）

---

## 5. 消息与回复（Message Create）

### 5.1 `on_message` 使用要点
- 忽略 bot 自己消息（防自触发循环）
- 结合 mention/reply 判断是否触发 AI
- 需要 `MESSAGE CONTENT INTENT` 才能读文本内容

### 5.2 回复上下文
- 回复 bot 消息时，建议带上：
  - 上一条 assistant 内容
  - 当前 user 回复
- 这是实现“连续对话感”的关键（你项目已采用）

---

## 6. Reaction 监听（收税机制核心）

### 6.1 推荐监听
- 优先使用 `on_raw_reaction_add`（不依赖消息缓存）

### 6.2 触发链路常见失败点
1. 目标消息不是图片（附件类型/URL 后缀不匹配）
2. emoji 配置值与实际 reaction 不一致（名称/ID/自定义格式）
3. bot 对该频道无 `Read Message History` 或看不到频道
4. 已有同 message 的 pending case（被去重）

### 6.3 排查建议
- 打印 `payload.emoji.name / payload.emoji.id / str(payload.emoji)`
- 打印当前配置 `shit_emoji`
- 确认频道权限与消息可读性

---

## 7. Moderation：Timeout（禁言）

### 7.1 权限与限制
- 需要 `Moderate Members`
- bot 的角色层级必须高于目标成员
- 超时时间有上限（官方限制）

### 7.2 代码要点
- 传入 UTC 时间
- 失败时捕获 HTTPException 并记录原因

---

## 8. 频道 NSFW 与内容策略

你的 Danbooru 策略建议：
- NSFW 频道强制 `rating:e`
- 非 NSFW 频道强制 `rating:s`

对应官方频道属性：
- `TextChannel.is_nsfw()`

---

## 9. 你当前项目的“权限最小检查清单”

1. OAuth2 scopes：`bot` + `applications.commands`
2. Bot 权限：至少包含本文件 2.2
3. Portal intents：Message Content / Server Members 已开启
4. 频道覆盖：bot 在触发频道可读历史、可发消息
5. 角色层级：bot 高于被 timeout 的成员

---

## 10. 对本项目的落地建议（短期）

- 为收税链路加结构化日志：
  - `emoji_received`, `emoji_expected`, `has_image`, `existing_case`
- 增加调试命令：`/config debug_tax on|off`
- 在 dashboard 增加“最近收税触发失败原因统计”
- 将关键权限检测做成启动自检并在 health 接口输出

---

## 11. 参考关键词（后续检索官方文档）

- OAuth2 URL Generator
- Gateway Intents
- Interactions / Application Commands
- Message Components
- Guild Member Timeout / Communication Disabled
- Permission Overwrites
