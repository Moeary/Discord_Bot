# Discord 命令文档

这个文件对应站内的 `/docs` 页面，尽量和代码里的命令目录保持同步。

## 普通用户

### AI

- `/ai chat`
  - 和 GLaDOS 聊天，支持带一张图。
- `/ai summary`
  - 总结当前频道最近聊天。
- `/ai draw`
  - AI 绘图或改图；可以只带图不写 prompt。
- `/ai image`
  - `/ai draw` 别名。
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
- `/fun roulette`
- `/fun coin`
- `/fun choose`
- `/fun eightball`
- `/fun waifu`
- `/fun lottery`
- `/fun ship`
- `/fun diagnose`
- `/fun rate`
- `/fun duel`
- `/fun leaderboard`

## 管理员

- `/config view`
  - 统一查看配置，推荐配合 `scope:guild` / `scope:global` / `scope:all`。
- `/config set`
  - 统一修改配置，推荐配合 `scope:guild` / `scope:global`。
- `/config global_view`
  - 兼容旧入口，等价于 `/config view scope:global`。
- `/config global_set`
  - 兼容旧入口，等价于 `/config set scope:global`。
- `/config tax_channel`
  - 设置税务频道。

## 图站档案约定

- 美图默认优先用 `safe_image_site_profile`
- 涩图默认优先用 `explicit_image_site_profile`
- 用户自己的 `/fun image_source` 和 `/fun image_tags` 会覆盖服务器默认值
- Rule34 默认只建议用于 `explicit` 模式

## 维护说明

- 命令描述和权限来源：`app/core/catalog.py`
- 人设文案来源：`data/personas.json`
- 站内文档页：`/docs`
- 控制台接口：`/api/dashboard`
