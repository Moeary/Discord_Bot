# DC Bot Paper Bridge

This Paper plugin bridges chat, player events, and online status between a Paper server and the DC Bot FastAPI app.

## Features

- **Chat bridge**: MC chat ↔ Discord channel (双向)
- **Player events**: join/quit → Discord 通知
- **Online players**: periodically reported to FastAPI (cached for DC query)
- **Offline tells**: DC users can leave messages for MC players, delivered on join
- **No history replay**: only messages sent after server start are broadcast

## Build

```powershell
$env:JAVA_HOME = "D:\Apps\Dev\JDK22"
.\gradlew.bat build
```

On Linux CI or a Linux server, use `./gradlew build`.

The manual `Paper Bridge Jar` GitHub Actions workflow builds the plugin against the official Paper API, uploads `build/libs/dc-bot-paper-bridge-<version>.jar` as a workflow artifact, and can publish it to a GitHub Release tagged as `paper-bridge-v<version>`.

## Paper Config

After the first server start, edit:

```text
plugins\DcBotPaperBridge\config.yml
```

Important values:

- `enabled`: set to `true` only when you want this Paper server to poll FastAPI.
- `api-base-url`: FastAPI base URL, usually `http://127.0.0.1:8000`.
- `server-id`: must match `minecraft_server_id` in the DC Bot guild settings.
- `token`: optional. If empty, FastAPI only accepts local/private network clients when `minecraft_allow_no_token` is enabled.

The Minecraft server can generate the shared secret with:

```text
/dcbotbridge token generate
```

Then put that value into FastAPI as `MINECRAFT_TOKEN` or the guild setting `minecraft_token`.

## FastAPI/Guild Settings

Set these for the Discord guild:

- `minecraft_bridge_enabled=true`
- `minecraft_server_id=default`
- `minecraft_server_address=<optional, for reference>`
- `minecraft_channel_id=<Discord text channel id, not guild/server id>`
- `minecraft_token=<same token as plugin, optional>`
- `minecraft_allow_no_token=true` for local/private no-token testing
- `MINECRAFT_ALLOWED_CLIENTS=<Paper server IP or CIDR>` when exposing FastAPI beyond localhost

Users can bind identity with `/minecraft bind <username>`.

## DC Bot Commands

- `/minecraft bind <username>` — bind your Minecraft username
- `/minecraft unbind` — unbind
- `/minecraft status` — view bridge status and your binding
- `/minecraft online` — query current online players on the MC server
- `/minecraft tell <username> <message>` — leave a message for an offline player (delivered on join)
