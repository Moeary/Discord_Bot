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
- `搬屎交税`
  - 别人给带图消息点到配置的 `shit` emoji 时，触发警告
  - 管理员回复某条带图消息 `税` / `交税` / `补税` 也可手动触发
  - 被点名的人需要去税务频道补发 3 张图
  - 超时未交税自动禁言 1 小时
- `其他娱乐功能`
  - `/fun fortune` 今日运势
  - `/fun roulette` 轮盘
  - `/fun waifu` 今日老婆/老公（同一天每个用户结果不同）
  - `/fun lottery` 每日抽签
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
```

说明：

- `.env` 现在只建议存放 URL、token、api key 这类环境信息。
- `data/providers.json` 负责声明“渠道”和“模型档案”，每个档案会绑定 `type / provider / adapter / model`。
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
- `pixi run dev`：开发模式启动 FastAPI
- `pixi run start`：普通启动

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
- `GET /api/health`
- `GET /api/dashboard`

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
- `/ai draw prompt:<描述> profile:<可选档案> model:<可选覆盖> size:<可选> variants:<1|2>`

### 娱乐

- `/fun danbooru tags:<标签>`
- `/fun fortune`
- `/fun roulette`
- `/fun coin`
- `/fun choose`
- `/fun eightball`
- `/fun waifu`
- `/fun lottery`
- `/fun ship`
- `/fun leaderboard`

### 配置

- `/config view`
- `/config global_view`
- `/config set key:<配置项> value:<值>`
- `/config global_set key:<配置项> value:<值>`
- `/config tax_channel channel:<频道>`

## 可调整配置项

### 全局配置

- `chat_model_profile`
- `chat_fallback_profiles`
- `draw_model_profile`
- `draw_fallback_profiles`
- `system_prompt`
- `summary_system_prompt`
- `max_chat_history`

### 服务器配置

- `ai_enabled`
- `fun_enabled`
- `tax_enabled`
- `tax_channel_id`
- `log_channel_id`
- `shit_emoji`
- `tax_required_images`
- `tax_payment_window_minutes`
- `mute_hours`
- `summary_limit`
- `danbooru_default_tags`
- `warn_text`

## `warn_text` 可用占位符

- `{user_mention}`
- `{tax_channel}`
- `{minutes}`
- `{required_images}`
- `{mute_hours}`

## 备注

- AI 默认系统提示词和总结提示词为 GLaDOS 风格，可在面板里改。
- 回复机器人消息会自动触发 AI 对话，并携带上一条 AI 回复与当前用户回复作为上下文。
- 直接 `@机器人` 说话也会触发 AI，对回复某条消息的场景会优先理解那条被回复的消息。
- `/ai chat` 和 `@机器人` 对话支持读图；`/ai summary` 默认只总结文字，不猜图片内容。
- 当主 AI 渠道失败时，会自动尝试 fallback 渠道，并直接把失败原因显示出来。
- `搬屎交税` 支持“发图消息 + 点指定 emoji”触发，也支持管理员回复关键字手动触发。
- 补税逻辑默认只认税务频道里的图片附件和常见图片链接。
- 如果没有配置 `tax_channel_id`，机器人仍会警告，但你最好尽快配置税务频道。
