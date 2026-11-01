package app.chainproxy.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.VpnService
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import app.chainproxy.MainActivity
import app.chainproxy.R
import io.nekohasekai.libbox.CommandServer
import io.nekohasekai.libbox.CommandServerHandler
import io.nekohasekai.libbox.Libbox
import io.nekohasekai.libbox.OverrideOptions
import io.nekohasekai.libbox.SetupOptions
import io.nekohasekai.libbox.SystemProxyStatus
import app.chainproxy.session.AppState
import app.chainproxy.session.SessionRunner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.io.File
import java.util.concurrent.Executors

private const val TAG = "ChainVpnService"

/**
 * Owns the sing-box core (libbox) and the TUN device. The service is started with ACTION_START and the path
 * of a ready sing-box JSON config; the config itself is produced by the app logic (or, in tests, pushed by adb).
 */
class ChainVpnService : VpnService(), CommandServerHandler {
    private val worker = Executors.newSingleThreadExecutor()
    private var server: CommandServer? = null
    private var platform: ChainPlatform? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var session: SessionRunner? = null
    private var sessionJob: kotlinx.coroutines.Job? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                promote()
                val path = intent.getStringExtra(EXTRA_CONFIG)
                if (path != null) worker.execute { start(File(path).readText()) }      // a ready config (emulator test)
                else if (session == null) beginSession()
            }
            ACTION_NEXT -> scope.launch { session?.next(); refreshNotification() }
            ACTION_PREV -> scope.launch { session?.prev(); refreshNotification() }
            ACTION_RESCAN -> scope.launch { session?.rescan(); refreshNotification() }
            ACTION_GOTO -> scope.launch { session?.goTo(intent.getIntExtra(EXTRA_INDEX, -1)); refreshNotification() }
            ACTION_STOP -> {
                Log.i(TAG, "ACTION_STOP received")
                worker.execute { stop() }
            }
        }
        return START_NOT_STICKY
    }

    private fun beginSession() {
        VpnState.set(Phase.Starting, "Preparing")
        val runner = SessionRunner(this, scope) { json -> worker.submit { start(json, markRunning = false) }.get() }
        session = runner
        sessionJob = scope.launch {
            val error = try { runner.run() } catch (e: Throwable) { Log.e(TAG, "session failed", e); e.message ?: e.javaClass.simpleName }
            if (error != null) {
                AppState.log("FAILED: $error")
                worker.execute { failAndStop(error) }
            } else {
                VpnState.set(Phase.Running)
                refreshNotification()
            }
        }
    }

    @Synchronized
    private fun failAndStop(reason: String) {
        cleanup()
        VpnState.set(Phase.Failed, reason)
        stopForegroundAndSelf()
    }

    private fun refreshNotification() {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, buildNotification(AppState.summary.value))
    }

    private fun promote() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "VPN status", NotificationManager.IMPORTANCE_LOW))
        val n = buildNotification("Connecting ...")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIFICATION_ID, n)
        }
    }

    private fun action(code: Int, label: String, act: String): NotificationCompat.Action = NotificationCompat.Action(
        0, label, PendingIntent.getService(this, code, Intent(this, ChainVpnService::class.java).setAction(act), PendingIntent.FLAG_IMMUTABLE))

    private fun buildNotification(text: String): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text.ifEmpty { "Connecting ..." })
            .setStyle(NotificationCompat.BigTextStyle().bigText(text.ifEmpty { "Connecting ..." }))
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(action(1, "Next", ACTION_NEXT))
            .addAction(action(2, "Stop", ACTION_STOP))
            .build()
    }

    @Synchronized
    private fun start(config: String, markRunning: Boolean = true) {
        if (server != null) return
        VpnState.set(Phase.Starting)
        try {
            Libbox.checkConfig(config)
            setup()
            val p = ChainPlatform(this, packageName)
            val s = Libbox.newCommandServer(this, p)
            s.start()
            s.startOrReloadService(config, OverrideOptions())
            platform = p
            server = s
            if (markRunning) VpnState.set(Phase.Running)
        } catch (e: Throwable) {
            Log.e(TAG, "start failed", e)
            VpnState.set(Phase.Failed, e.message ?: e.javaClass.simpleName)
            cleanup()
            stopForegroundAndSelf()
        }
    }

    @Synchronized
    private fun stop() {
        Log.i(TAG, "stop requested (running=${server != null})")
        if (server == null) {
            cleanup()
            stopForegroundAndSelf()
            return
        }
        VpnState.set(Phase.Stopping)
        cleanup()
        VpnState.set(Phase.Stopped)
        stopForegroundAndSelf()
    }

    private fun cleanup() {
        sessionJob?.cancel()
        sessionJob = null
        session?.stop()
        session = null
        runCatching { server?.closeService() }.onFailure { Log.w(TAG, "closeService failed", it) }
        runCatching { server?.close() }.onFailure { Log.w(TAG, "close failed", it) }
        platform?.close()
        server = null
        platform = null
        Log.i(TAG, "core closed")
    }

    private fun stopForegroundAndSelf() {
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun setup() {
        if (isSetUp) return
        val base = filesDir.resolve("core").apply { mkdirs() }
        Libbox.setup(SetupOptions().apply {
            basePath = base.path
            workingPath = base.path
            tempPath = cacheDir.path
            logMaxLines = 300
            fixAndroidStack = true
        })
        isSetUp = true
    }

    override fun onRevoke() {          // the user turned the VPN off in the system UI
        worker.execute { stop() }
    }

    override fun onDestroy() {
        scope.cancel()
        worker.execute { cleanup() }
        worker.shutdown()
        super.onDestroy()
    }

    // ---- CommandServerHandler ---------------------------------------------------------------
    override fun serviceStop() {
        worker.execute { stop() }
    }

    override fun serviceReload() {}
    override fun getSystemProxyStatus() = SystemProxyStatus()
    override fun setSystemProxyEnabled(enabled: Boolean) {}
    override fun connectSSHAgent(): Int = throw UnsupportedOperationException()
    override fun triggerNativeCrash() {}
    override fun writeDebugMessage(message: String) {
        Log.d(TAG, message)
    }

    companion object {
        const val ACTION_START = "app.chainproxy.START"
        const val ACTION_STOP = "app.chainproxy.STOP"
        const val ACTION_NEXT = "app.chainproxy.NEXT"
        const val ACTION_PREV = "app.chainproxy.PREV"
        const val ACTION_RESCAN = "app.chainproxy.RESCAN"
        const val ACTION_GOTO = "app.chainproxy.GOTO"
        const val EXTRA_INDEX = "index"
        const val EXTRA_CONFIG = "config"
        const val DEFAULT_CONFIG = "config.json"
        private const val CHANNEL = "vpn"
        private const val NOTIFICATION_ID = 1
        @Volatile private var isSetUp = false
    }
}
