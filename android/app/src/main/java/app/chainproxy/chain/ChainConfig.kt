package app.chainproxy.chain

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/**
 * Settings, mirroring DEFAULTS in chain.py (same keys in the saved JSON). Ports are the desktop defaults:
 * unusual numbers that other tools (v2rayN 10808, Clash 7890/9090) do not use.
 */
@Serializable
data class ChainConfig(
    @SerialName("mixed_port") val mixedPort: Int = 42815,
    @SerialName("api_port") val apiPort: Int = 42816,
    @SerialName("lantern_port") val lanternPort: Int = 42819,
    @SerialName("top_k") val topK: Int = 5,
    @SerialName("top_k_exit") val topKExit: Int = 12,
    @SerialName("top_k_profiles") val topKProfiles: Int = 3,
    @SerialName("tcp_timeout") val tcpTimeout: Double = 3.0,
    @SerialName("delay_timeout_ms") val delayTimeoutMs: Int = 7000,
    @SerialName("check_urls") val checkUrls: List<String> = listOf(
        "https://www.gstatic.com/generate_204", "https://cp.cloudflare.com/generate_204"),
    @SerialName("strict_urls") val strictUrls: List<String> = listOf("https://gemini.google.com"),
    @SerialName("blocked_countries") val blockedCountries: List<String> = listOf("IR"),
    @SerialName("direct_suffixes") val directSuffixes: List<String> = listOf(".ir"),
    @SerialName("private_direct") val privateDirect: Boolean = true,
    @SerialName("log_level") val logLevel: String = "warn",
    @SerialName("geo_url") val geoUrl: String = "https://ipinfo.io/json",
    @SerialName("geo_fallback_urls") val geoFallbackUrls: List<String> = listOf("https://api.country.is/", "https://ipwho.is/"),
    @SerialName("verify_timeout") val verifyTimeout: Int = 12,
    @SerialName("rank_by_speed") val rankBySpeed: Boolean = false,
    @SerialName("lantern_enabled") val lanternEnabled: Boolean = true,
    @SerialName("lantern_timeout") val lanternTimeout: Int = 90,
    @SerialName("watchdog_seconds") val watchdogSeconds: Int = 60,
    @SerialName("watchdog_failures") val watchdogFailures: Int = 2,
    @SerialName("update_check_hours") val updateCheckHours: Int = 6,
    @SerialName("update_repo") val updateRepo: String = "",          // "" = the built-in release repository
    // Sources (on the desktop these live in subs.txt / profiles_*.txt)
    @SerialName("first_subscription") val firstSubscription: String = "",
    @SerialName("exit_subscription") val exitSubscription: String = DEFAULT_EXIT_SUBSCRIPTION,
    @SerialName("first_profiles") val firstProfiles: String = "",
    @SerialName("exit_profiles") val exitProfiles: String = "",
    // Android only: per-app split tunnelling. "all" = every app, "include" = only the listed apps, "exclude" = all but them.
    @SerialName("split_mode") val splitMode: String = "all",
    @SerialName("split_apps") val splitApps: List<String> = emptyList(),
) {
    /** Values normalized the way load_cfg does (bare hosts become https URLs). */
    fun normalized() = copy(
        strictUrls = strictUrls.map(::normalizeUrl).filter { it.isNotEmpty() },
        checkUrls = checkUrls.map(::normalizeUrl).filter { it.isNotEmpty() },
        geoFallbackUrls = geoFallbackUrls.map(::normalizeUrl).filter { it.isNotEmpty() },
        geoUrl = normalizeUrl(geoUrl),
    )

    fun toJson(): String = codec.encodeToString(this)

    companion object {
        /** The public "best" list of the GeminiRoute project: the default exit hop, same as on the desktop. */
        const val DEFAULT_EXIT_SUBSCRIPTION = "https://alizn7.github.io/GeminiRoute/sub/best.txt"

        private val codec = Json { ignoreUnknownKeys = true; encodeDefaults = true; prettyPrint = true }

        /** Tolerant: a damaged file gives the defaults rather than a crash at start-up. */
        fun fromJson(text: String?): ChainConfig =
            runCatching { codec.decodeFromString<ChainConfig>(text.orEmpty()) }.getOrDefault(ChainConfig()).normalized()
    }
}
