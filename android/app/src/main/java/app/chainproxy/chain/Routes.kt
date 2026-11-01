package app.chainproxy.chain

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.coroutineScope
import kotlin.coroutines.coroutineContext

/** What the app needs from the running sing-box: delay tests per outbound and switching the selector. */
interface CoreApi {
    suspend fun delay(tag: String, url: String, timeoutMs: Int): Double?
    suspend fun select(tag: String)
}

/** One line of the route table. */
data class RouteRow(
    val tag: String, val label: String, val source: String, val delayMs: Double,
    val active: Boolean, val rejected: String? = null,
)

/**
 * Port of chain.App's routing part: rank the routes (chains first, then exit hop alone, then first hop alone; inside
 * a group by source priority tier, then speed), switch to the next/previous one that passes verification.
 * Tiers: first hop 1 = Lantern, 2 = subscription, 3 = profiles; exit hop 1 = subscription, 2 = profiles.
 */
class RouteManager(
    private val cfg: ChainConfig,
    private val core: CoreApi,
    private val verifier: suspend () -> Pair<Boolean, String>,
    private val log: (String) -> Unit = {},
) {
    private val lock = Mutex()
    private var names: Map<String, String> = emptyMap()
    private var tiers: Map<String, Int> = emptyMap()
    private var firstTags: List<String> = emptyList()
    private var exitTags: List<String> = emptyList()
    var rank: List<String> = emptyList(); private set
    private var delays: Map<String, Double?> = emptyMap()
    private val rejected = LinkedHashMap<String, String>()
    var idx = -1; private set
    var lastInfo = ""; private set

    private val _rows = MutableStateFlow<List<RouteRow>>(emptyList())
    val rows: StateFlow<List<RouteRow>> = _rows.asStateFlow()

    fun setNodes(a: Map<String, Node>, b: Map<String, Node>, tier: Map<String, Int>) {
        names = (a + b).mapValues { it.value.name }
        tiers = tier
        firstTags = a.keys.toList()
        exitTags = b.keys.toList()
    }

    private fun tierOf(tag: String) = tiers[tag] ?: 1

    fun sourceLabel(tag: String): String = tag.split("-").joinToString(" + ") { t ->
        val table = if (t.startsWith("A")) mapOf(1 to "Lantern", 2 to "Subscription", 3 to "Profile")
        else mapOf(1 to "Subscription", 2 to "Profile")
        table[tierOf(t)] ?: "?"
    }

    fun label(tag: String): String = tag.split("-").joinToString(" -> ") { "$it:${(names[it] ?: it).take(26)}" }

    private suspend fun measureAll(tags: List<String>): Map<String, Double?> {
        val gate = Semaphore(12)
        return coroutineScope {
            tags.map { tag ->
                async {
                    gate.withPermit {
                        val ds = ArrayList<Double>()
                        for (url in cfg.checkUrls) {
                            val d = core.delay(tag, url, cfg.delayTimeoutMs) ?: return@withPermit tag to null
                            ds.add(d)
                        }
                        tag to ds.average()
                    }
                }
            }.awaitAll().toMap()
        }
    }

    suspend fun buildRank() = lock.withLock { buildRankLocked() }

    private suspend fun buildRankLocked() {
        val chains = firstTags.flatMap { a -> exitTags.map { b -> "$a-$b" } }
        val res = measureAll(chains + exitTags + firstTags)
        delays = res
        rejected.clear()
        rank = computeRank(chains, res)
        idx = -1
        log("${rank.size} routes usable (${ordered(chains, res).size} chains, ${ordered(exitTags, res).size} B-only, " +
            "${ordered(firstTags, res).size} A-only)")
        publish()
    }

    private fun key(t: String): List<Double> = t.split("-").map { tierOf(it).toDouble() }

    private fun ordered(tags: List<String>, res: Map<String, Double?>): List<String> =
        tags.filter { res[it] != null }.sortedWith { x, y ->
            val kx = key(x) + res.getValue(x)!!
            val ky = key(y) + res.getValue(y)!!
            var c = 0
            for (i in 0 until minOf(kx.size, ky.size)) { c = kx[i].compareTo(ky[i]); if (c != 0) break }
            if (c != 0) c else kx.size.compareTo(ky.size)
        }

    private fun computeRank(chains: List<String>, res: Map<String, Double?>): List<String> =
        if (cfg.rankBySpeed) (chains + exitTags + firstTags).filter { res[it] != null }.sortedBy { res.getValue(it) }
        else ordered(chains, res) + ordered(exitTags, res) + ordered(firstTags, res)

    /** Test hook: the ranking a given set of delays would give, without touching the core. */
    fun rankFor(res: Map<String, Double?>): List<String> =
        computeRank(firstTags.flatMap { a -> exitTags.map { b -> "$a-$b" } }, res)

    private fun delayOf(tag: String) = delays[tag] ?: 0.0

    private fun summary(i: Int, tag: String, info: String) =
        "[${i + 1}/${rank.size}] ${label(tag)}  ${"%.0f".format(delayOf(tag))}ms  exit: $info"

    /** Switch to the next (step > 0) or previous suitable route; the first one that verifies wins. */
    suspend fun go(step: Int): String = lock.withLock { goLocked(step) }

    private suspend fun goLocked(step: Int): String {
        if (rank.isEmpty()) return "no usable route"
        val n = rank.size
        val start = idx
        for (k in 0 until n) {
            if (!coroutineContext.isActive) return "stopping"
            val i = if (start < 0) (if (step > 0) k else n - 1 - k) else Math.floorMod(start + step * (k + 1), n)
            val tag = rank[i]
            try {
                core.select(tag)
            } catch (e: Exception) {
                log("select failed $tag ${e.message}")
                continue
            }
            val (ok, info) = verifier()
            if (ok) {
                idx = i; lastInfo = info; rejected.remove(tag)
                publish()
                return summary(i, tag, info)
            }
            rejected[tag] = info
            log("  skip $tag: $info")
            publish()
        }
        if (start in 0 until n) runCatching { core.select(rank[start]) }
        return "no route passed verification; run a rescan or relax the strict sites"
    }

    /** Switch to a specific ranked route (verified); on failure the previous one is selected again. */
    suspend fun goTo(i: Int): String = lock.withLock {
        if (i !in rank.indices) return@withLock "no such route"
        val prev = idx
        val tag = rank[i]
        var ok = false
        var info: String
        try {
            core.select(tag)
            val r = verifier(); ok = r.first; info = r.second
        } catch (e: Exception) {
            info = "select failed: ${e.message}"
        }
        if (ok) {
            idx = i; lastInfo = info; rejected.remove(tag)
            publish()
            return@withLock summary(i, tag, info)
        }
        rejected[tag] = info
        if (prev in rank.indices) runCatching { core.select(rank[prev]) }.onFailure { log("could not go back to the previous route: ${it.message}") }
        publish()
        "route rejected (${label(tag)}): $info"
    }

    suspend fun rescan(): String = lock.withLock {
        buildRankLocked()
        goLocked(1)
    }

    suspend fun status(): String = lock.withLock {
        if (idx < 0) return@withLock "no active route"
        val tag = rank[idx]
        val (_, info) = verifier()
        summary(idx, tag, info)
    }

    private fun publish() {
        _rows.value = rank.mapIndexed { i, t ->
            RouteRow(t, label(t), sourceLabel(t), delayOf(t), i == idx, rejected[t])
        }
    }
}
