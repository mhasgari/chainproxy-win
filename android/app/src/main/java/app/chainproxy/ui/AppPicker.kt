package app.chainproxy.ui

import android.content.Intent
import android.content.pm.PackageManager
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import app.chainproxy.R

private data class AppEntry(val pkg: String, val label: String)

/** Launcher apps with a search box and checkboxes; [onDone] gets the selected package names. */
@Composable
fun AppPicker(initial: Set<String>, onDone: (Set<String>) -> Unit) {
    val ctx = LocalContext.current
    val apps = remember {
        val pm = ctx.packageManager
        pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), PackageManager.MATCH_ALL)
            .map { AppEntry(it.activityInfo.packageName, it.loadLabel(pm).toString()) }
            .filter { it.pkg != ctx.packageName }.distinctBy { it.pkg }.sortedBy { it.label.lowercase() }
    }
    val chosen = remember { mutableStateListOf<String>().apply { addAll(initial) } }
    var query by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().padding(12.dp)) {
        OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.search)) }, singleLine = true)
        LazyColumn(Modifier.weight(1f)) {
            items(apps.filter { query.isBlank() || it.label.contains(query, true) || it.pkg.contains(query, true) }, key = { it.pkg }) { a ->
                Row(Modifier.fillMaxWidth().clickable { if (a.pkg in chosen) chosen.remove(a.pkg) else chosen.add(a.pkg) }, verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(a.pkg in chosen, { if (it) chosen.add(a.pkg) else chosen.remove(a.pkg) })
                    Column { Text(a.label); Text(a.pkg, style = androidx.compose.material3.MaterialTheme.typography.bodySmall) }
                }
            }
        }
        Button(onClick = { onDone(chosen.toSet()) }, Modifier.fillMaxWidth()) { Text(stringResource(R.string.done)) }
    }
}
