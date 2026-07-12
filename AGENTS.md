# DC_Bot 代理说明

这个仓库是一个 `Discord Bot + FastAPI` 项目，主目标是娱乐向机器人和一个轻量控制台。代理在这里工作时，优先理解“入口在哪里、状态写到哪里、命令和配置从哪里来”，不要把已经存在的文档内容重复写进来。

## 工作边界

- 代码编排入口在 [app/main.py](app/main.py)，这里把配置、状态存储、AI、图站、Minecraft 桥接、FastAPI 路由和网页模板串起来。
- 运行入口在 [app/run.py](app/run.py)，它只负责读取 `HOST` / `PORT` 并启动 uvicorn。
- 环境变量与默认路径都在 [app/core/config.py](app/core/config.py)；新增配置先看这里。
- 命令和配置元数据的权威来源在 [app/core/catalog.py](app/core/catalog.py)；`/docs` 页面和 [docs/commands.md](docs/commands.md) 都是从这里导出的文档面。
- HTTP 路由应保持薄层，业务逻辑尽量放在 [app/services/](app/services/)；Discord 交互逻辑主要在 [app/bot/](app/bot/)。
- 持久化运行态写入 [data/state.json](data/state.json)；[data/providers.json](data/providers.json) 和 [data/personas.json](data/personas.json) 是配置数据，不要当作静态源码处理。
- `paper-bridge/` 是独立的 Java/Paper 插件边界，单独构建，不要把它和 Python 主程序混为一体。

## 常用命令

- 推荐开发流程：`pixi install` → `pixi run check` → `pixi run dev`
- 生产或普通启动：`pixi run start`
- 备用方式：创建 venv，`pip install -r requirements.txt`，再运行 `uvicorn app.main:app --reload`
- Docker 启动以 [docker-compose.yml](docker-compose.yml) 为准，会挂载 `./data` 到容器内的 `/app/data`
- `paper-bridge` 单独构建，Windows 用 [paper-bridge/gradlew.bat](paper-bridge/gradlew.bat)，其他系统用 `./gradlew`
- Paper 插件编译需要 JDK 21+（本机 `D:\Apps\Dev\JDK22`），Gradle wrapper 会自动下载 Gradle 8.12.1。编译前需设置 `JAVA_HOME`：
  ```powershell
  cd paper-bridge
  $env:JAVA_HOME = "D:\Apps\Dev\JDK22"
  .\gradlew.bat build
  ```
  产物位于 `paper-bridge/build/libs/dc-bot-paper-bridge-<version>.jar`。注意系统默认 `java` 指向 JDK 17，直接运行 `gradlew.bat build` 会报 `release version 21 not supported`。

## 代码约定

- 新增或修改命令时，先改 [app/core/catalog.py](app/core/catalog.py)，再同步 [docs/commands.md](docs/commands.md) 和 `/docs` 相关页面。
- 新增或修改配置时，优先检查 [app/core/config.py](app/core/config.py) 是否需要默认值或环境变量映射。
- 如果变更影响机器人行为，优先定位到对应服务层文件，而不是在路由或入口层堆逻辑。
- `.env` 只放密钥和运行环境值；模板以 [.env.example](.env.example) 为准。
- Discord slash 命令在测试环境下可能复制到 `DISCORD_TEST_GUILD_ID`，排查同步问题时先看这个环境变量。
- Minecraft 互通最容易出错的是 `minecraft_server_id`、`minecraft_channel_id` 和 token/allow-no-token 的组合，改动前要核对两端配置是否一致。

## 参考文档

下面这些文档已经覆盖了大部分细节，AGENTS.md 只保留工作导航：

- [README.md](README.md)
- [docs/commands.md](docs/commands.md)
- [paper-bridge/README.md](paper-bridge/README.md)
