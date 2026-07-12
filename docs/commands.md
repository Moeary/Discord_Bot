# Discord 命令文档

这个文件对应站内的 `/docs` 页面，尽量和代码里的命令目录保持同步。

## 普通用户

### AI

- `/ai chat`
  - 和 GLaDOS 聊天，支持带一张图；贴网页 URL 会自动抓取，明显要求“搜索/最新/当前”时会自动搜索。
- `/ai summary`
  - 总结当前频道最近聊天。
- `/ai draw`
  - AI 绘图或改图；可以只带图不写 prompt。
- `@GLaDOS ...`
  - 直接聊天、要图、整活。
- `回复 GLaDOS ...`
  - 续聊、继续追问。
- `消息右键 -> GLaDOS 改图`
  - 对某条带图消息直接发起改图。

### 娱乐

- `/fun image`
  - 通用随机图入口，可选 `safe` / `explicit` 和图站档案。
- `/fun danbooru`
  - 固定走 Danbooru。
- `/fun rule34`
  - 固定走 Rule34，仅限 NSFW 频道。
- `/fun pretty`
  - 快速来张美图。
- `/fun lewd`
  - 快速来张涩图，仅限 NSFW 频道。
- `/fun image_prefs`
  - 查看你自己的图站默认配置。
- `/fun image_source`
  - 设置你自己的美图/涩图默认图站档案。
- `/fun image_tags`
  - 设置你自己的美图/涩图默认 tag。
- `/fun image_sites`
  - 查看当前有哪些图站档案。
- `/fun sauce`
  - 用 SauceNAO 反查图片来源。
- `@GLaDOS 搜图`
  - 直接带图，或者回复一条带图消息搜图。
- `消息右键 -> GLaDOS 搜图`
  - 对某条图片消息直接反查来源。
- `/fun fortune`
- `/fun coin`
- `/fun eightball`
- `/fun waifu`
  - 抽今天的 safe 二次元老婆图，并尽量带出作品和角色名。
- `/fun ship`
- `/fun duel`
- `/fun leaderboard`

### 不用 Slash 也能做的事

- `@GLaDOS 你好`
  - 直接聊天。
- `@GLaDOS 查一下今天的某个新闻`
  - 自动用搜索结果补上下文后回答。
- `@GLaDOS 总结这个链接 https://example.com`
  - 自动抓取网页正文后回答。
- `回复 GLaDOS 继续`
  - 接着上一轮继续聊。
- `@GLaDOS draw 一只猫娘`
  - 直接触发绘图。
- `回复一张图 @GLaDOS 改图，换成赛博风`
  - 直接改图。
- `@GLaDOS 来张美图`
  - 抽安全图。
- `@GLaDOS 来张色图`
  - 抽涩图，仅限 NSFW 频道。
- `@GLaDOS 搜图`
  - 带图或回复图片消息反查来源。
- `@GLaDOS 今日运势`
  - 直接看运势。
- `@GLaDOS 抛硬币`
  - 直接抛硬币。
- `@GLaDOS 8ball 我今天该不该熬夜`
  - 直接问八球。
- `@GLaDOS 老婆`
  - 直接抽今日 safe 二次元老婆。

## 管理员

- `/config view`
  - 一次看完当前服务器配置和全局配置。
- `/config set`
  - 按 key 自动修改服务器或全局配置，不再需要手填 scope。

## 图站档案约定

- 美图默认优先用 `safe_image_site_profile`
- 涩图默认优先用 `explicit_image_site_profile`
- 用户自己的 `/fun image_source` 和 `/fun image_tags` 会覆盖服务器默认值
- Rule34 默认只建议用于 `explicit` 模式

## AI 联网预算

- 自动搜索只适合需要当前事实的问题；普通聊天不会为了“今天心情如何”这类话题去搜索。
- 网页抓取和搜索上下文受全局配置限制：`ai_web_fetch_limit`、`ai_web_search_result_limit`、`ai_web_context_char_limit`、`ai_web_fetch_max_bytes`、`ai_web_fetch_snippet_chars`。
- 想省 token 或 API 费用时，可用 `/config set ai_web_tools_enabled false` 关闭，或分别关闭 `ai_web_fetch_enabled` / `ai_web_search_enabled`。

## 维护说明

- 命令描述和权限来源：`app/core/catalog.py`
- 人设文案来源：`data/personas.json`
- 站内文档页：`/docs`
- 控制台接口：`/api/dashboard`
