package app.chainproxy.update

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * In-app update from GitHub releases. Android releases are tagged `android-vX.Y.Z` (the desktop uses `vX.Y.Z`) and are
 * never "Latest", so the release LIST is read. The APK is checked against the sha256 published next to it; Android itself
 * refuses an APK that is not signed with the installed app's key.
 */
object UpdateChecker {
    /** Release repository, kept encoded so no account or repository name appears as plain text in the app. */
    val DEFAULT_REPO: String = String(java.util.Base64.getDecoder().decode("bWhhc2dhcmkvY2hhaW5wcm94eQ=="))

    const val TAG_PREFIX = "android-v"
    private val KNOWN_ABIS = listOf("arm64-v8a", "armeabi-v7a", "x86_64", "x86")

    data class Info(val version: String, val apkUrl: String, val sha256Url: String?, val notes: String)

    fun parseVersion(v: String): List<Int> = v.removePrefix("v").split('.', '-').mapNotNull { it.toIntOrNull() }

    fun isNewer(candidate: String, current: String): Boolean {
        val a = parseVersion(candidate)
        val b = parseVersion(current)
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrElse(i) { 0 }
            val y = b.getOrElse(i) { 0 }
            if (x != y) return x > y
        }
        return false
    }

    /** The newest published Android release that is newer than [current], or null. */
    fun pick(releasesJson: String, current: String, abis: List<String> = emptyList()): Info? {
        val list: JsonArray = Json.parseToJsonElement(releasesJson).jsonArray
        var best: Info? = null
        for (r in list.map { it.jsonObject }) {
            val tag = r["tag_name"]?.jsonPrimitive?.contentOrNull ?: continue
            if (!tag.startsWith(TAG_PREFIX)) continue
            if (r["draft"]?.jsonPrimitive?.boolean == true || r["prerelease"]?.jsonPrimitive?.boolean == true) continue
            val version = tag.removePrefix(TAG_PREFIX)
            if (!isNewer(version, current) || (best != null && !isNewer(version, best.version))) continue
            val assets = r["assets"]?.jsonArray?.map { it.jsonObject }.orEmpty()
            val apks = assets.filter { it.name().endsWith(".apk") }
            // one APK per CPU architecture: the first of the device's ABIs (best first) that has a build, else a universal one
            val apk = abis.firstNotNullOfOrNull { abi -> apks.firstOrNull { it.name().endsWith("-$abi.apk") } }
                ?: apks.firstOrNull { a -> KNOWN_ABIS.none { a.name().endsWith("-$it.apk") } } ?: continue
            val sum = assets.firstOrNull { it.name() == apk.name() + ".sha256" }
            best = Info(version, apk.url(), sum?.url(), r["body"]?.jsonPrimitive?.contentOrNull.orEmpty())
        }
        return best
    }

    private fun JsonObject.name() = this["name"]?.jsonPrimitive?.contentOrNull.orEmpty()
    private fun JsonObject.url() = this["browser_download_url"]?.jsonPrimitive?.contentOrNull.orEmpty()

    private fun get(url: String): ByteArray {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 20000; c.readTimeout = 60000
        c.setRequestProperty("User-Agent", "chainproxy-android")
        c.setRequestProperty("Accept", "application/vnd.github+json")
        try {
            if (c.responseCode >= 400) throw java.io.IOException("HTTP ${c.responseCode}")
            return c.inputStream.use { it.readBytes() }
        } finally { c.disconnect() }
    }

    suspend fun check(repo: String, current: String, api: String = "https://api.github.com/repos/${repo.ifEmpty { DEFAULT_REPO }}/releases?per_page=30"): Result<Info?> =
        withContext(Dispatchers.IO) { runCatching { pick(get(api).toString(Charsets.UTF_8), current, android.os.Build.SUPPORTED_ABIS.toList()) } }

    suspend fun downloadAndInstall(ctx: Context, info: Info, progress: (String) -> Unit) = withContext(Dispatchers.IO) {
        try {
            progress("Downloading ...")
            val dir = File(ctx.cacheDir, "updates").apply { deleteRecursively(); mkdirs() }
            val apk = File(dir, "update.apk")
            apk.writeBytes(get(info.apkUrl))
            val want = info.sha256Url?.let { get(it).toString(Charsets.UTF_8).trim().split(Regex("\\s+")).first().lowercase() }
            val got = MessageDigest.getInstance("SHA-256").digest(apk.readBytes()).joinToString("") { "%02x".format(it) }
            if (want == null) throw IllegalStateException("the release has no .sha256 file")
            if (want != got) { apk.delete(); throw IllegalStateException("checksum mismatch") }
            val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.files", apk)
            ctx.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
            progress("Checksum OK. Confirm the installation in the system dialog.")
        } catch (e: Exception) {
            progress("Update failed: ${e.message ?: e.javaClass.simpleName}")
        }
    }
}
