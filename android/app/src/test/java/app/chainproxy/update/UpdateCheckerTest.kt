package app.chainproxy.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateCheckerTest {
    private fun release(tag: String, apk: Boolean = true, sum: Boolean = true, pre: Boolean = false) =
        """{"tag_name":"$tag","draft":false,"prerelease":$pre,"body":"notes","assets":[""" +
            listOfNotNull(
                if (apk) """{"name":"ChainProxy-1.apk","browser_download_url":"https://x/$tag.apk"}""" else null,
                if (sum) """{"name":"ChainProxy-1.apk.sha256","browser_download_url":"https://x/$tag.sha"}""" else null).joinToString(",") + "]}"

    @Test fun versionOrder() {
        assertTrue(UpdateChecker.isNewer("0.2.0", "0.1.9"))
        assertTrue(UpdateChecker.isNewer("1.0", "0.9.9"))
        assertFalse(UpdateChecker.isNewer("0.1.0", "0.1.0"))
        assertFalse(UpdateChecker.isNewer("0.1", "0.1.0"))
        assertTrue(UpdateChecker.isNewer("0.10.0", "0.9.0"))
    }

    @Test fun picksTheApkOfTheDevicesArchitecture() {
        val json = """[{"tag_name":"android-v1.0.0","body":"","assets":[
            {"name":"ChainProxy-1.0.0-arm64-v8a.apk","browser_download_url":"https://x/a64"},
            {"name":"ChainProxy-1.0.0-arm64-v8a.apk.sha256","browser_download_url":"https://x/a64.sha"},
            {"name":"ChainProxy-1.0.0-armeabi-v7a.apk","browser_download_url":"https://x/a32"},
            {"name":"ChainProxy-1.0.0-armeabi-v7a.apk.sha256","browser_download_url":"https://x/a32.sha"}]}]"""
        assertEquals("https://x/a64", UpdateChecker.pick(json, "0.1.0", listOf("arm64-v8a", "armeabi-v7a"))!!.apkUrl)
        assertEquals("https://x/a32", UpdateChecker.pick(json, "0.1.0", listOf("armeabi-v7a"))!!.apkUrl)
        assertEquals("https://x/a32.sha", UpdateChecker.pick(json, "0.1.0", listOf("armeabi-v7a"))!!.sha256Url)
        assertNull(UpdateChecker.pick(json, "0.1.0", listOf("x86_64")))            // no build for this CPU
    }

    @Test fun picksNewestAndroidReleaseOnly() {
        val json = "[" + listOf(release("v9.0.0"), release("android-v0.1.5"), release("android-v0.2.0"), release("android-v0.3.0", pre = true),
            release("android-v0.4.0", apk = false)).joinToString(",") + "]"
        val info = UpdateChecker.pick(json, "0.1.0")!!
        assertEquals("0.2.0", info.version)
        assertEquals("https://x/android-v0.2.0.apk", info.apkUrl)
        assertEquals("https://x/android-v0.2.0.sha", info.sha256Url)
        assertNull(UpdateChecker.pick(json, "0.2.0"))
    }
}
