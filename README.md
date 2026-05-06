# DC 娱乐机器人

这是一个从零搭的 `Discord Bot + FastAPI` 项目，目标是做成偏娱乐向的 DC 机器人，同时带一个简单可视化控制台。

## 已做功能

- `AI 对话`
  - Discord 命令：`/ai chat`（支持可选图片）
  - FastAPI 路由：`POST /api/ai/chat`
- `AI 总结对话`
  - Discord 命令：`/ai summary`
  - FastAPI 路由：`POST /api/ai/summary`
- `AI 绘图`
  - Discord 命令：`/ai draw`
  - FastAPI 路由：`POST /api/ai/draw`、`POST /api/ai/draw/result`
- `Danbooru 随机找图`
  - Discord 命令：`/fun danbooru`
  - Danbooru 登录信息从环境变量读取
  - NSFW 频道默认 `rating:e`，非 NSFW 频道强制 `rating:s`
- `图站档案与用户偏好`
  - 支持 `danbooru` / `rule34`
  - 支持为美图和涩图分别设置默认图站与默认 tag
  - 支持 `@机器人 来张美图` / `@机器人 来张色图`
- `搬屎交税`
  - 别人给带图消息点到配置的 `shit` emoji 时，触发警告
  - 管理员回复某条带图消息 `税` / `交税` / `补税` 也可手动触发
  - 被点名的人需要去税务频道补发 3 张图
  - 超时未交税自动禁言 1 小时
- `其他娱乐功能`
  - `/fun fortune` 今日运势
  - `/fun coin` 抛硬币
  - `/fun eightball` 是非题
  - `/fun waifu` 今日老婆/老公（safe 二次元角色图）
  - 欢迎消息
  - 答题自助身份组
  - `/fun leaderboard` 榜单
- `可视化面板`
  - `GET /dashboard`
  - 查看状态、改全局设置、改服务器设置、测试 AI、看挂起税单

## 目录结构

```text
app/
  api/routes/        FastAPI 路由
  bot/               Discord Bot 逻辑
  core/              环境变量与配置目录
  models/            状态模型
  services/          OpenRouter / Danbooru / 状态存储 / 娱乐逻辑
  web/               Dashboard 模板和静态资源
```

## 环境变量

复制 `.env.example` 为 `.env` 后填写：

```env
DISCORD_TOKEN=你的机器人 token
DISCORD_TEST_GUILD_ID=测试服务器 ID，可选

AI_PROVIDER_FILE=data/providers.json
PERSONA_FILE=data/personas.json
GRSAI_BASE_URL=https://grsaiapi.com/v1
GRSAI_DRAW_BASE_URL=https://grsaiapi.com/v1
GRSAI_API_KEY=你的 grsai 聊天 key
GRSAI_DRAW_API_KEY=你的 grsai 绘图 key

OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_API_KEY=你的 OpenRouter key
OPENROUTER_SITE_URL=
OPENROUTER_SITE_NAME=

CUSTOM_BASE_URL=
CUSTOM_DRAW_BASE_URL=
CUSTOM_CHAT_API_KEY=可选的自定义聊天 key
CUSTOM_DRAW_API_KEY=可选的自定义绘图 key

DANBOORU_USERNAME=你的 danbooru 用户名
DANBOORU_API_KEY=你的 danbooru api key
RULE34_API_BASE_URL=https://api.rule34.xxx
RULE34_POST_BASE_URL=https://rule34.xxx
RULE34_USER_ID=你的 rule34 用户 id
RULE34_API_KEY=你的 rule34 api key
SAUCENAO_BASE_URL=https://saucenao.com/search.php
SAUCENAO_API_KEY=你的 SauceNAO key
```

说明：

- `.env` 现在只建议存放 URL、token、api key 这类环境信息。
- `data/providers.json` 负责声明“渠道”和“模型档案”，每个档案会绑定 `type / provider / adapter / model`。
- `data/personas.json` 负责声明“机器人人设档案”，包括 system prompt、summary prompt 和 fun 文案。
- 聊天目前统一按 `OpenAI 兼容 /chat/completions` 走；绘图目前支持 `grsai_draw_completions` 和 `grsai_draw_nano_banana` 两种适配器。
- `state.json` 只负责记录当前选中的 `chat_model_profile / draw_model_profile` 和群设置。
- 老配置仍然兼容，默认会自动映射到 `legacy-chat / legacy-draw`。
- `STATE_FILE` 默认是 `data/state.json`，机器人运行后的设置和统计会持久化到这里。

## 安装与启动

### 推荐：Pixi

```bash
pixi install
pixi run check
pixi run dev
```

如果 `pixi` 默认缓存目录权限有问题，可以改用项目内缓存：

```bash
set PIXI_CACHE_DIR=%CD%\.pixi-cache
pixi install
pixi run check
pixi run dev
```

常用命令：

- `pixi run check`：检查项目能否正常导入
- `pixi run dev`：开发模式启动 FastAPI，读取 `.env` 里的 `HOST` / `PORT`
- `pixi run start`：普通启动，读取 `.env` 里的 `HOST` / `PORT`

### 备用：pip / venv

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

启动后：

- 面板地址：`http://127.0.0.1:8000/dashboard`
- 健康检查：`http://127.0.0.1:8000/api/health`

## 路由说明

### 面板与状态

- `GET /dashboard`
- `GET /docs`
- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/docs`

### AI

- `POST /api/ai/chat`（支持 `image_urls`）
- `POST /api/ai/summary`（默认不读图片提示）
- `POST /api/ai/draw`
- `POST /api/ai/draw/result`

### 设置

- `GET /api/settings/global`
- `PATCH /api/settings/global`
- `GET /api/settings/guild/{guild_id}`
- `PATCH /api/settings/guild/{guild_id}`

### 税务与统计

- `GET /api/tax/pending`
- `GET /api/stats/{guild_id}`

## Discord 命令说明

### AI

- `/ai chat prompt:<内容> image:<可选图片> profile:<可选档案>`
- `/ai summary limit:<消息数>`
- `/ai draw prompt:<可留空> image:<可选图片> profile:<可选档案> model:<可选覆盖> size:<可选> variants:<1|2>`

### 娱乐

- `/fun image style:<safe|explicit> tags:<可选> profile:<可选图站档案>`
- `/fun danbooru tags:<标签>`
- `/fun rule34 tags:<标签>`
- `/fun pretty tags:<可选> profile:<可选图站档案>`
- `/fun lewd tags:<可选> profile:<可选图站档案>`
- `/fun image_prefs`
- `/fun image_source style:<safe|explicit> profile:<档案>`
- `/fun image_tags style:<safe|explicit> tags:<标签>`
- `/fun image_sites`
- `/fun sauce image:<可选图片> url:<可选图片链接>`
- `/fun fortune`
- `/fun coin`
- `/fun eightball`
- `/fun waifu`
- `/fun ship`
- `/fun duel`
- `/fun leaderboard`

### Minecraft

- `/minecraft bind username:<Minecraft 用户名>`
- `/minecraft unbind`
- `/minecraft status`

### 配置

- `/config view`
- `/config set key:<配置项> value:<值>`

## 可调整配置项

### 全局配置

- `chat_model_profile`
- `chat_fallback_profiles`
- `draw_model_profile`
- `draw_fallback_profiles`
- `persona_profile`
- `max_chat_history`

### 服务器配置

- `ai_enabled`
- `fun_enabled`
- `tax_enabled`
- `minecraft_bridge_enabled`
- `minecraft_server_id`
- `minecraft_server_address`
- `minecraft_channel_id`
- `minecraft_token`
- `minecraft_allow_no_token`
- `minecraft_max_message_length`
- `welcome_channel_id`
- `welcome_text`
- `verification_channel_id`
- `verification_role_id`
- `verification_question`
- `verification_answer`
- `verification_success_text`
- `tax_channel_id`
- `log_channel_id`
- `shit_emoji`
- `tax_required_images`
- `tax_payment_window_minutes`
- `mute_hours`
- `summary_limit`
- `danbooru_default_tags`
- `safe_image_site_profile`
- `explicit_image_site_profile`
- `safe_image_default_tags`
- `explicit_image_default_tags`
- `warn_text`

## `warn_text` 可用占位符

- `{user_mention}`
- `{tax_channel}`
- `{minutes}`
- `{required_images}`
- `{mute_hours}`

## Minecraft 双向聊天桥

FastAPI 侧新增了 `/api/minecraft/...` 接口，Paper 插件工程暂放在 `temp/dc_bot`，不会进入主程序 git 跟踪范围。插件默认是关闭的，只有 `plugins/DcBotPaperBridge/config.yml` 里 `enabled: true` 时才会轮询 FastAPI。插件只保留很薄的配置：`enabled`、`api-base-url`、`server-id`、`token`、轮询间隔和消息格式；Discord guild、频道、token、绑定关系都在 FastAPI/机器人状态里配置。

最小配置：

1. 在 `.env` 里设置：
   - `MINECRAFT_BRIDGE_ENABLED=true`
   - `MINECRAFT_GUILD_ID=<Discord 服务器 ID>`
   - `MINECRAFT_SERVER_ID=default`
   - `MINECRAFT_SERVER_ADDRESS=127.0.0.1:30001`
   - `MINECRAFT_CHANNEL_ID=<要同步的 Discord 文本频道 ID，不是服务器 ID>`
   - `MINECRAFT_TOKEN=<可选，和插件一致>`
   - `MINECRAFT_ALLOWED_CLIENTS=<可选，Paper 来源 IP/CIDR 白名单>`
2. 在 Paper 插件配置 `plugins/DcBotPaperBridge/config.yml` 里设置：
   - `enabled: true`
   - `api-base-url: "http://127.0.0.1:8000"`
   - `server-id: "default"`
   - `token: "<和 FastAPI 一致，可空>"`
3. 用户用 `/minecraft bind <username>` 绑定身份；Discord 同步到游戏时会显示为 `<username> 消息`。

`MINECRAFT_GUILD_ID` 可以不填：没填时会优先复用 `DISCORD_TEST_GUILD_ID`，或者按 `MINECRAFT_CHANNEL_ID` 对应的 Discord 频道自动判断。

如果 `minecraft_token` 留空，FastAPI 只允许本机、内网或链路本地地址直连，并且仍会做 `server_id` 校验、消息长度限制和短窗口限速。跨公网时建议同时设置 `MINECRAFT_TOKEN`、`MINECRAFT_ALLOW_NO_TOKEN=false` 和 `MINECRAFT_ALLOWED_CLIENTS`，例如 `203.0.113.10` 或 `203.0.113.0/24`。

## Rule34 凭据怎么拿

Rule34 现在的 API 访问需要 `user_id + api_key`。代码已经按这个格式接好了，你只要把它们填进 `.env` 里的 `RULE34_USER_ID` 和 `RULE34_API_KEY`。

建议流程：

1. 注册并登录 [rule34.xxx](https://rule34.xxx)。
2. 打开账号设置页：[https://rule34.xxx/index.php?page=account&s=options](https://rule34.xxx/index.php?page=account&s=options)
3. 找到 `API Access Credentials`。
4. 如果还没看到 key，就勾 `Generate New Key?` 然后保存。
5. 长字符串是 `api_key`，短数字是 `user_id`。
6. 分别填进项目 `.env`。

我参考了这些资料来核对当前流程：
- [rule34Py: How to set Rule34 api credentials](https://b3yc0d3.github.io/rule34Py/guides/api-credentials.html)
- [Rule34 API](https://api.rule34.xxx/)

## 备注

- AI 的系统提示词和总结提示词现在完全来自 `data/personas.json` 里的当前 `persona_profile`。
- 你后面如果要切 RP，只要新增 persona，然后把 `persona_profile` 切过去就行。
- `/config set` 现在会按 key 自动判断写入 guild 还是 global，不用再手填 `scope`。
- 回复机器人消息会自动触发 AI 对话，并携带上一条 AI 回复与当前用户回复作为上下文。
- 直接 `@机器人` 说话也会触发 AI，对回复某条消息的场景会优先理解那条被回复的消息。
- `/ai chat` 和 `@机器人` 对话支持读图；`/ai summary` 默认只总结文字，不猜图片内容。
- `/ai draw` 现在支持“只带参考图不写 prompt”的改图模式；右键消息 `GLaDOS 改图` 也能直接对某条图片消息起手。
- 不用 slash 的情况下，也可以直接 `@机器人` 或回复机器人来聊天、绘图、改图、搜图、来张美图/色图、看运势、抛硬币、问 8ball、抽老婆。
- 当主 AI 渠道失败时，会自动尝试 fallback 渠道，并直接把失败原因显示出来。
- 浏览器里的命令文档在 `/docs`；FastAPI 的 Swagger 被挪到了 `/api/docs`。
- `搬屎交税` 支持“发图消息 + 点指定 emoji”触发，也支持管理员回复关键字手动触发。
- 补税逻辑默认只认税务频道里的图片附件和常见图片链接。
- 如果没有配置 `tax_channel_id`，机器人仍会警告，但你最好尽快配置税务频道。
