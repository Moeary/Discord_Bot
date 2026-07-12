package com.dcbot.paperbridge;

import com.google.gson.Gson;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;
import io.papermc.paper.event.player.AsyncChatEvent;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer;
import org.bukkit.Bukkit;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.scheduler.BukkitTask;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

public final class DcBotPaperBridgePlugin extends JavaPlugin implements Listener {
    private final Gson gson = new Gson();
    private final PlainTextComponentSerializer plainText = PlainTextComponentSerializer.plainText();
    private final SecureRandom secureRandom = new SecureRandom();

    private HttpClient httpClient;
    private BukkitTask pollTask;
    private HttpServer httpServer;
    private boolean bridgeEnabled;
    private String apiBaseUrl;
    private String serverId;
    private String token;
    private String messageFormat;
    private int pollIntervalTicks;
    private int requestTimeoutMs;
    private int maxMessageLength;
    private int httpPort;
    private int lastMessageId;
    private boolean firstPoll = true;
    private volatile String lastError = "";
    private volatile String lastPoll = "never";
    private volatile long lastErrorLogAt = 0L;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        getConfig().options().copyDefaults(true);
        saveConfig();
        loadBridgeConfig();
        Bukkit.getPluginManager().registerEvents(this, this);
        startPoller();
        startHttpServer();
        if (bridgeEnabled) {
            getLogger().info("DC Bot Paper bridge enabled for server-id=" + serverId + ", api=" + apiBaseUrl);
        } else {
            getLogger().info("DC Bot Paper bridge is installed but disabled. Set enabled: true in config.yml to start it.");
        }
    }

    @Override
    public void onDisable() {
        if (pollTask != null) {
            pollTask.cancel();
            pollTask = null;
        }
        if (httpServer != null) {
            httpServer.stop(0);
            httpServer = null;
        }
    }

    // --- Player join / quit events ---

    @EventHandler
    public void onPlayerJoin(PlayerJoinEvent event) {
        if (!bridgeEnabled) return;
        Player player = event.getPlayer();
        sendPlayerEvent(player, "join");
        // Fetch pending tells for this player
        Bukkit.getScheduler().runTaskAsynchronously(this, () -> fetchAndDeliverTells(player));
    }

    @EventHandler
    public void onPlayerQuit(PlayerQuitEvent event) {
        if (!bridgeEnabled) return;
        sendPlayerEvent(event.getPlayer(), "quit");
    }

    private void sendPlayerEvent(Player player, String eventType) {
        Bukkit.getScheduler().runTaskAsynchronously(this, () -> {
            Map<String, String> payload = new LinkedHashMap<>();
            payload.put("server_id", serverId);
            payload.put("event_type", eventType);
            payload.put("player_name", player.getName());
            payload.put("player_uuid", player.getUniqueId().toString());

            HttpRequest request = authed(HttpRequest.newBuilder(endpoint("/api/minecraft/events/player")))
                    .version(HttpClient.Version.HTTP_1_1)
                    .timeout(Duration.ofMillis(requestTimeoutMs))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(gson.toJson(payload), StandardCharsets.UTF_8))
                    .build();
            try {
                HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
                if (response.statusCode() / 100 != 2) {
                    rememberError("player event post failed: HTTP " + response.statusCode());
                }
            } catch (IOException | InterruptedException ex) {
                if (ex instanceof InterruptedException) Thread.currentThread().interrupt();
                rememberError("player event post failed: " + ex.getClass().getSimpleName() + ": " + ex.getMessage());
            }
        });
    }

    private void fetchAndDeliverTells(Player player) {
        String encodedServerId = URLEncoder.encode(serverId, StandardCharsets.UTF_8);
        String encodedName = URLEncoder.encode(player.getName(), StandardCharsets.UTF_8);
        String path = "/api/minecraft/servers/" + encodedServerId + "/tells/" + encodedName;
        HttpRequest request = authed(HttpRequest.newBuilder(endpoint(path)))
                .version(HttpClient.Version.HTTP_1_1)
                .timeout(Duration.ofMillis(requestTimeoutMs))
                .GET()
                .build();
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) return;
            PendingTellsResponse tells = gson.fromJson(response.body(), PendingTellsResponse.class);
            if (tells == null || tells.tells == null || tells.tells.isEmpty()) return;
            // Deliver tells on main thread
            Bukkit.getScheduler().runTask(this, () -> {
                for (PendingTell tell : tells.tells) {
                    if (tell == null || tell.message == null) continue;
                    String from = (tell.from_user != null && !tell.from_user.isBlank()) ? tell.from_user : "DC";
                    player.sendMessage(Component.text("§7[DC留言] §f" + from + "§7: §f" + tell.message));
                }
            });
        } catch (IOException | InterruptedException ex) {
            if (ex instanceof InterruptedException) Thread.currentThread().interrupt();
            getLogger().warning("Failed to fetch pending tells for " + player.getName() + ": " + ex.getMessage());
        }
    }

    // --- Chat bridge ---

    @EventHandler
    public void onAsyncChat(AsyncChatEvent event) {
        if (!bridgeEnabled) return;
        String message = cleanMessage(plainText.serialize(event.message()));
        if (message.isBlank()) return;
        sendChatEvent(event.getPlayer(), message);
    }

    // --- Commands ---

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0 || args[0].equalsIgnoreCase("status")) {
            sender.sendMessage("DC Bot bridge: enabled=" + bridgeEnabled
                    + ", server-id=" + serverId
                    + ", api=" + apiBaseUrl
                    + ", token=" + (!token.isBlank())
                    + ", httpPort=" + httpPort
                    + ", lastPoll=" + lastPoll
                    + ", lastMessageId=" + lastMessageId
                    + ", firstPoll=" + firstPoll
                    + (lastError.isBlank() ? "" : ", lastError=" + lastError));
            return true;
        }
        if (args[0].equalsIgnoreCase("reload")) {
            reloadConfig();
            loadBridgeConfig();
            startPoller();
            startHttpServer();
            sender.sendMessage("DC Bot bridge config reloaded.");
            return true;
        }
        if (args[0].equalsIgnoreCase("token")) {
            if (args.length >= 2 && args[1].equalsIgnoreCase("generate")) {
                token = generateToken();
                getConfig().set("token", token);
                saveConfig();
                sender.sendMessage("Generated bridge token. Put this value into FastAPI MINECRAFT_TOKEN or minecraft_token:");
                sender.sendMessage(token);
                return true;
            }
            if (token.isBlank()) {
                sender.sendMessage("Bridge token is empty. Use /dcbotbridge token generate to create one.");
            } else {
                sender.sendMessage("Bridge token:");
                sender.sendMessage(token);
            }
            return true;
        }
        return false;
    }

    // --- Config ---

    private void loadBridgeConfig() {
        bridgeEnabled = getConfig().getBoolean("enabled", false);
        apiBaseUrl = trimTrailingSlash(getConfig().getString("api-base-url", "http://127.0.0.1:8000"));
        serverId = getConfig().getString("server-id", "default").trim();
        token = getConfig().getString("token", "").trim();
        messageFormat = getConfig().getString("minecraft-message-format", "<%username%> %message%");
        pollIntervalTicks = Math.max(5, getConfig().getInt("poll-interval-ticks", 20));
        int connectTimeoutMs = Math.max(500, getConfig().getInt("connect-timeout-ms", 3000));
        requestTimeoutMs = Math.max(500, getConfig().getInt("request-timeout-ms", 5000));
        maxMessageLength = Math.max(1, Math.min(500, getConfig().getInt("max-message-length", 300)));
        httpPort = Math.max(0, getConfig().getInt("http-port", 25580));
        httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofMillis(connectTimeoutMs))
                .build();
    }

    // --- Poller ---

    private void startPoller() {
        if (pollTask != null) {
            pollTask.cancel();
            pollTask = null;
        }
        if (!bridgeEnabled) return;
        pollTask = Bukkit.getScheduler().runTaskTimerAsynchronously(
                this,
                this::pollDiscordMessages,
                pollIntervalTicks,
                pollIntervalTicks
        );
    }

    private void sendChatEvent(Player player, String message) {
        if (!bridgeEnabled) return;
        Bukkit.getScheduler().runTaskAsynchronously(this, () -> {
            Map<String, String> payload = new LinkedHashMap<>();
            payload.put("server_id", serverId);
            payload.put("player_uuid", player.getUniqueId().toString());
            payload.put("player_name", player.getName());
            payload.put("message", message);
            payload.put("world", player.getWorld().getName());

            HttpRequest request = authed(HttpRequest.newBuilder(endpoint("/api/minecraft/events/chat")))
                    .version(HttpClient.Version.HTTP_1_1)
                    .timeout(Duration.ofMillis(requestTimeoutMs))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(gson.toJson(payload), StandardCharsets.UTF_8))
                    .build();
            try {
                HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
                if (response.statusCode() / 100 != 2) {
                    rememberError("chat post failed: HTTP " + response.statusCode() + " " + response.body());
                } else if (response.body().contains("\"accepted\":false")) {
                    rememberError("chat post was not delivered by FastAPI: " + response.body());
                } else {
                    lastError = "";
                }
            } catch (IOException | InterruptedException ex) {
                if (ex instanceof InterruptedException) Thread.currentThread().interrupt();
                rememberError("chat post failed: " + ex.getClass().getSimpleName() + ": " + ex.getMessage());
            }
        });
    }

    private void pollDiscordMessages() {
        if (!bridgeEnabled) return;
        String encodedServerId = URLEncoder.encode(serverId, StandardCharsets.UTF_8);
        String path = "/api/minecraft/servers/" + encodedServerId + "/messages?after=" + lastMessageId + "&limit=20";
        HttpRequest request = authed(HttpRequest.newBuilder(endpoint(path)))
                .version(HttpClient.Version.HTTP_1_1)
                .timeout(Duration.ofMillis(requestTimeoutMs))
                .GET()
                .build();
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) {
                rememberError("poll failed: HTTP " + response.statusCode() + " " + response.body());
                return;
            }
            BridgeMessages messages = gson.fromJson(response.body(), BridgeMessages.class);
            if (messages == null || messages.messages == null) {
                return;
            }
            // On first poll, just record the latest ID without broadcasting
            if (firstPoll) {
                for (BridgeMessage message : messages.messages) {
                    if (message != null && message.id > lastMessageId) {
                        lastMessageId = message.id;
                    }
                }
                if (messages.next_after > lastMessageId) {
                    lastMessageId = messages.next_after;
                }
                firstPoll = false;
                lastPoll = "ok (warmup)";
                lastError = "";
                getLogger().info("Bridge warmed up, starting from message id=" + lastMessageId);
                return;
            }
            for (BridgeMessage message : messages.messages) {
                if (message == null || message.id <= lastMessageId || message.content == null) continue;
                lastMessageId = Math.max(lastMessageId, message.id);
                broadcastDiscordMessage(message);
            }
            if (messages.next_after > lastMessageId) {
                lastMessageId = messages.next_after;
            }
            lastPoll = "ok";
            lastError = "";
        } catch (IOException | InterruptedException ex) {
            if (ex instanceof InterruptedException) Thread.currentThread().interrupt();
            rememberError("poll failed: " + ex.getClass().getSimpleName() + ": " + ex.getMessage());
        }
    }

    private void broadcastDiscordMessage(BridgeMessage message) {
        String username = cleanUsername(message.username);
        String content = cleanMessage(message.content);
        if (content.isBlank()) return;
        String line = messageFormat
                .replace("%username%", username)
                .replace("%display_name%", safeText(message.display_name))
                .replace("%discord_user_id%", safeText(message.discord_user_id))
                .replace("%message%", content);
        Bukkit.getScheduler().runTask(this, () -> Bukkit.broadcast(Component.text(line)));
    }

    // --- Embedded HTTP server ---

    private void startHttpServer() {
        if (httpServer != null) {
            httpServer.stop(0);
            httpServer = null;
        }
        if (!bridgeEnabled || httpPort <= 0) return;
        try {
            httpServer = HttpServer.create(new InetSocketAddress(httpPort), 0);
            httpServer.createContext("/api/players", new PlayersHandler());
            httpServer.setExecutor(null);
            httpServer.start();
            getLogger().info("Bridge HTTP server started on port " + httpPort);
        } catch (IOException ex) {
            getLogger().warning("Failed to start HTTP server on port " + httpPort + ": " + ex.getMessage());
        }
    }

    private class PlayersHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            // Verify token
            String authHeader = exchange.getRequestHeaders().getFirst("Authorization");
            String xToken = exchange.getRequestHeaders().getFirst("X-DC-Bot-Token");
            String providedToken = null;
            if (authHeader != null && authHeader.toLowerCase().startsWith("bearer ")) {
                providedToken = authHeader.substring(7).trim();
            } else if (xToken != null) {
                providedToken = xToken.trim();
            }
            if (!token.isBlank() && (providedToken == null || !providedToken.equals(token))) {
                sendJson(exchange, 401, "{\"error\":\"invalid token\"}");
                return;
            }

            List<String> playerNames = new ArrayList<>();
            for (Player p : Bukkit.getOnlinePlayers()) {
                playerNames.add(p.getName());
            }
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("server_id", serverId);
            result.put("online_count", playerNames.size());
            result.put("max_players", Bukkit.getMaxPlayers());
            result.put("players", playerNames);
            sendJson(exchange, 200, gson.toJson(result));
        }
    }

    private void sendJson(HttpExchange exchange, int statusCode, String json) throws IOException {
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(statusCode, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    // --- Utilities ---

    private HttpRequest.Builder authed(HttpRequest.Builder builder) {
        if (!token.isBlank()) {
            builder.header("Authorization", "Bearer " + token);
            builder.header("X-DC-Bot-Token", token);
        }
        return builder;
    }

    private URI endpoint(String path) {
        return URI.create(apiBaseUrl + path);
    }

    private String cleanMessage(String raw) {
        String cleaned = safeText(raw).replace("\r", "").trim();
        if (cleaned.length() > maxMessageLength) {
            return cleaned.substring(0, Math.max(0, maxMessageLength - 1)) + "…";
        }
        return cleaned;
    }

    private String cleanUsername(String raw) {
        String cleaned = safeText(raw).replaceAll("[^A-Za-z0-9_]", "_");
        if (cleaned.length() > 16) cleaned = cleaned.substring(0, 16);
        if (cleaned.length() >= 3) return cleaned;
        return "Discord";
    }

    private String safeText(String raw) {
        return raw == null ? "" : raw.replaceAll("[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F\\x7F]", "");
    }

    private String trimTrailingSlash(String value) {
        String trimmed = value == null ? "" : value.trim();
        while (trimmed.endsWith("/")) trimmed = trimmed.substring(0, trimmed.length() - 1);
        return trimmed.isBlank() ? "http://127.0.0.1:8000" : trimmed;
    }

    private String generateToken() {
        byte[] bytes = new byte[32];
        secureRandom.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private void rememberError(String error) {
        String trimmed = error.length() > 240 ? error.substring(0, 240) : error;
        long now = System.currentTimeMillis();
        if (!trimmed.equals(lastError) || now - lastErrorLogAt > 60_000L) {
            getLogger().warning(trimmed);
            lastErrorLogAt = now;
        }
        lastError = trimmed;
        lastPoll = "failed";
    }

    // --- Data classes ---

    private static final class BridgeMessages {
        List<BridgeMessage> messages;
        int next_after;
    }

    private static final class BridgeMessage {
        int id;
        String username;
        String display_name;
        String discord_user_id;
        String content;
    }

    private static final class PendingTellsResponse {
        String player_name;
        List<PendingTell> tells;
    }

    private static final class PendingTell {
        int id;
        String from_user;
        String message;
        String created_at;
    }
}
