# راهنمای توسعه‌دهنده — Chain Proxy

این سند معماری، تصمیم‌های طراحی، قراردادهای داخلی و روش توسعه و تست را شرح می‌دهد. راهنمای کاربر در [USER-GUIDE.md](USER-GUIDE.md) است.

---

## ۱. نمای کلی

Chain Proxy یک **هماهنگ‌کننده** (orchestrator) روی هسته‌ی [sing-box](https://github.com/SagerNet/sing-box) است. خودش ترافیک را جابه‌جا نمی‌کند؛ کارش این است:

1. ساپسکریپشن‌ها را بگیرد و به outboundهای sing-box تبدیل کند،
2. نودهای مناسب را انتخاب و اعتبارسنجی کند،
3. یک کانفیگ با مسیرهای زنجیره‌ای (A → B) بسازد و هسته را اجرا کند،
4. مسیرها را اندازه بگیرد، رتبه‌بندی کند و بهترین را فعال کند،
5. پروکسی ویندوز را تنظیم و هنگام خروج برگرداند،
6. در طول اجرا مسیر/هسته را نگهبانی و در صورت نیاز جایگزین کند،
7. فرمان‌های کاربر (next/prev/…) را از پنجره، کنسول یا خط فرمان بپذیرد.

**اصل طراحی:** وابستگی‌ها صفر (فقط کتابخانه‌ی استاندارد Python)، یک فایل منطق (`chain.py`)، و هر مسیر خرابی یک پاسخ روشن داشته باشد (پیام خطا، ترمیم خودکار یا بازگشت به حالت امن).

```
                        ┌────────────┐   ┌─────────────┐
 Run.bat ─► setup.ps1 ─►│  Python    │   │ offline\    │
 (میانبر)   (نصب/ترمیم) │  + tkinter │   │ (جایگزین)   │
                        └─────┬──────┘   └─────────────┘
                              ▼
        ┌──────────────────────────────────────────────────┐
        │ gui.py (tkinter)        chain.py CLI (کنسول)     │
        └───────────────┬──────────────────┬───────────────┘
                        │ start_session()  │ control_send()
                        ▼                  ▼
   ┌────────────────────────────────────────────────────────────┐
   │ chain.py                                                   │
   │  fetch_nodes → pick/validate → build_config → Core.start   │
   │  App.build_rank → App.go/go_to → verify → sys_proxy_set    │
   │  watchdog · control server (127.0.0.1:42817)               │
   └───────────┬───────────────────────────────┬────────────────┘
               │ Clash API 127.0.0.1:42816     │ HKCU\...\Internet Settings
               ▼                               ▼
         sing-box (mixed 127.0.0.1:42815)   پروکسی سیستم ویندوز ◄── Chrome/Edge
               │
        A ──► B ──► اینترنت
```

---

## ۲. ساختار پروژه

| مسیر | نقش |
|---|---|
| `Run.bat` | نقطه‌ی ورود (دابل‌کلیک/میانبر). `setup.ps1` را اجرا می‌کند؛ در خطا `pause`. حالت‌ها: بدون آرگومان (پنجره)، `cli`، `shortcut`. |
| `setup.ps1` | راه‌انداز: یافتن/نصب Python، `chain.py ensure`، ساخت میانبرها، اجرای برنامه. |
| `chain.py` | تمام منطق: پارس، کانفیگ، هسته، منابع و اولویت‌ها، موتور Lantern، پروکسی ویندوز، نگهبان، کنترل، به‌روزرسانی، CLI. |
| `gui.py` | پنجره‌ی tkinter (ttk، تم `clam` با رنگ‌های اختصاصی)، Settings چهار زبانه، تک‌نمونه‌بودن، به‌روزرسانی؛ لایه‌ی نازک روی `chain.App`. |
| `tray.py` | آیکون ناحیه‌ی اعلان‌ها با ctypes (بدون بسته‌ی اضافه): پنجره‌ی مخفی روی ترد جدا، منو، balloon، `TaskbarCreated`، `WM_ENDSESSION`. |
| `assets/` | PNGهای آیکون (16..256)؛ پنجره فقط با `iconphoto` آن‌ها را می‌گذارد. `chainproxy.ico` با `dev/make_icons.py` ساخته می‌شود. |
| `quit.bat` | مثل `stop.bat` + بستن پنجره‌ی داخل tray (`chain.py quit`)؛ نصب‌کننده/حذف‌کننده/به‌روزرسانی از آن استفاده می‌کنند. |
| `profiles_first.txt`, `profiles_exit.txt` | لینک‌های v2ray کاربر برای هاپ اول/آخر (در گیت نیستند). |
| `engine/` | `chainlantern.exe` بازشده (در زمان اجرا؛ در گیت نیست). |
| `config.json` | تنظیمات کاربر (روی پیش‌فرض‌های `DEFAULTS` ادغام می‌شود). |
| `LICENSE` | MIT. |
| `subs.example.txt` | قالب `subs.txt` (خط اول نمونه، خط دوم لیست best از GeminiRoute). |
| `subs.txt` | خط اول = ساپسکریپشن A، خط دوم = B. `#` توضیح است. **در گیت نیست** (`.gitignore`)؛ اگر نباشد از قالب `subs.example.txt` ساخته می‌شود و بسته‌ی انتشار (`make package`) هم همیشه همین قالب را به‌جای فایل کاربر می‌گذارد. |
| `next.bat`, `stop.bat`, `start.bat` | میانبرهای CLI (`next`, `off`, `Run.bat cli`). `next.bat` و `stop.bat` خودشان Python را می‌یابند (`%LOCALAPPDATA%\Programs\Python`، بعد `py -3`، بعد `python`) و به PATH وابسته نیستند؛ حذف‌کننده‌ی نصب‌کننده هم از `stop.bat` استفاده می‌کند. |
| `chainproxy.ico` | آیکون میانبر و پنجره. |
| `offline/` | فایل‌های جایگزین دانلود (نصب‌کننده‌ی Python، zip هسته). نصب‌کننده‌ی Full این پوشه را پر می‌کند. |
| `installer/` | اسکریپت Inno Setup (`chainproxy.iss`) و `THIRD-PARTY-NOTICES.txt` نسخه‌ی Full. ساخت: `make installer` (داخل VM). |
| `docs/` | `QUICKSTART.md` + PDF آن (`make pdf`)، `USER-GUIDE.md`، `DEVELOPER.md`. |
| `tests/` | `run_tests.py`، `gui_smoke.py` و `mock_core.py` (بخش ۱۱). |
| `dev/` | ابزار توسعه (در بسته‌ی کاربر نیست): آزمایشگاه e2e (`dev/lab/`)، راننده‌ی VM ویندوز (`dev/vm/`)، `setup-cachyos.sh`، `package.py`، `make_pdf.py`، `make_installer.py`، `make_icons.py`، `build_lantern.py` و `dev/lantern/chainlantern/main.go` (راه‌انداز Go موتور Lantern). راهنما: [dev/README.md](../dev/README.md). |
| `Makefile`, `CLAUDE.md`, `.claude/` | فرمان‌های توسعه و تنظیمات Claude Code. |
| **تولیدشده در زمان اجرا** | |
| `core/` | `sing-box.exe` و DLLهای همراه. |
| `cache/A.txt`, `cache/B.txt` | آخرین ساپسکریپشن دانلودشده (جایگزین هنگام قطع). |
| `runtime/config.json`, `runtime/core.log` | کانفیگ و لاگ هسته. حاوی اطلاعات حساس‌اند. |
| `.proxy_state.json` | تنظیمات **اصلی** پروکسی ویندوز پیش از دست‌کاری (برای بازگردانی). |
| `.shortcuts_done` | نشانه‌ی ساخته‌شدن میانبر (برای اینکه حذف عمدی کاربر نادیده نشود). |

---

## ۳. جریان راه‌اندازی (`start_session`)

ترتیب مراحل در `chain.start_session(cfg)`؛ هر مرحله‌ی ناموفق با `SystemExit`/پیام روشن قطع می‌شود و `cleanup()` اجرا می‌شود.

1. **تک‌نمونه‌بودن:** اگر سوکت کنترل پاسخ بدهد → «already running».
2. **بازیابی خرابی قبلی:** اگر `.proxy_state.json` وجود دارد → `sys_proxy_restore()`.
3. **منابع:** `load_sources()`؛ اگر هنوز لینک نمونه‌اند (`subs_are_placeholder`) خطای روشن.
4. **هسته:** `ensure_core()` (بخش ۶).
5. **پورت‌ها:** `port_free()` برای `mixed_port` و `api_port` (تا ۵ ثانیه تلاش مجدد).
6. **نودها:** `fetch_nodes()` برای A و B → `pick()` (بخش ۴).
7. **کانفیگ:** `build_config(modern=True)` → `core_check()`؛ اگر رد شد `modern=False` → دوباره `core_check()`؛ اگر باز رد شد خطا با متن هسته.
8. **اجرای هسته:** `Core.start(conf)`؛ منتظر ماندن تا Clash API جواب بدهد (حداکثر ~۱۵ ثانیه).
9. **رتبه‌بندی:** `App.build_rank()`؛ سپس `App.go(1)` اولین مسیرِ تأییدشده را فعال می‌کند.
10. **پروکسی ویندوز:** `sys_proxy_set()` (فقط **بعد از** داشتن یک مسیر سالم).
11. **سرویس‌های پس‌زمینه:** سرور کنترل، نگهبان.

نکته: کنسول و GUI هر دو از همین تابع استفاده می‌کنند؛ تفاوتشان فقط لایه‌ی تعامل است (`App.console()` یا `gui.GUI`).

---

## ۴. پارس نودها و انتخاب

### ۴.۱ `parse_node(link) -> (name, outbound) | None`
هر لینک به یک outbound sing-box تبدیل می‌شود. خطای پارس همیشه `None` برمی‌گرداند و هرگز استثنا نمی‌دهد (ساپسکریپشن‌ها پر از ورودی‌های خراب‌اند).

| طرح | outbound | یادداشت |
|---|---|---|
| `vless://` | `vless` | `flow`، TLS و REALITY (`pbk`, `sid`, `fp`)، `packet_encoding: xudp` |
| `vmess://` (JSON در base64) | `vmess` | `aid`، `scy`، `net` → transport |
| `trojan://` | `trojan` | TLS همیشه فعال (`force=True`) |
| `ss://` | `shadowsocks` | SIP002 و قالب قدیمی؛ نودِ دارای `plugin=` رد می‌شود |
| `hysteria2://`, `hy2://` | `hysteria2` | `obfs=salamander`؛ TCP-probe نمی‌شود |

Transportها در `transport_block`: `ws` (با تبدیل `?ed=N` به `max_early_data`)، `grpc`، `httpupgrade`، `h2/http`. TLS در `tls_block`.

### ۴.۲ `fetch_nodes(src, label)`
`src` می‌تواند URL، مسیر فایل محلی یا لینک تکی نود باشد. دانلود موفق در `cache/<label>.txt` ذخیره می‌شود؛ در شکست از کش خوانده می‌شود. بدنه اگر طرح `xxx://` نداشته باشد به‌عنوان base64 (معمولی/urlsafe، بدون padding) رمزگشایی می‌شود. نودهای تکراری با `node_key = (type, server, port, uuid|password)` حذف می‌شوند.

### ۴.۳ `pick(nodes, k, timeout, prefix, validator)`
1. **TCP probe موازی** (`tcp_ms`، ۶۴ رشته) و مرتب‌سازی نودهای پاسخ‌گو بر اساس زمان.
2. اگر هیچ‌کدام پاسخ ندادند (مثلاً probe مستقیم فیلتر است)، همه‌ی نودها به‌ترتیب اصلی ماندگار می‌شوند و تصمیم به تست سرتاسری سپرده می‌شود.
3. **اعتبارسنجی با هسته:** از `3×k` نودِ اول، آن‌هایی که `node_valid` (`sing-box check` روی یک کانفیگ کوچک تک‌outbound) را بگذرانند برگزیده می‌شوند. اگر **همه** رد شوند (احتمال خرابی خود چک) نودها بدون اعتبارسنجی استفاده می‌شوند و لاگ هشدار می‌دهد.
4. تگ‌گذاری: `A1…Ak` و `B1…Bk`.

> دلیل: یک نود ناسازگار در کانفیگ مشترک، شروع کل هسته را می‌شکند. اعتبارسنجی تکی این خطر را از بین می‌برد.

---

## ۵. کانفیگ sing-box و مدل مسیر

### ۵.۱ ساختار (`build_config`)
```jsonc
{
  "log": {"level": "warn", "timestamp": true},
  "inbounds": [{"type": "mixed", "tag": "in", "listen": "127.0.0.1", "listen_port": 42815}],
  "outbounds": [
    {"type": "direct", "tag": "direct"},
    {"...": "A1..Ak, B1..Bk (outbound هر نود، tag = A1 …)"},
    {"...": "B2 با \"tag\": \"A1-B2\", \"detour\": \"A1\"   // زنجیره: کلاینت → A1 → B2"},
    {"type": "selector", "tag": "route",
     "outbounds": ["A1-B1", "A1-B2", "...", "B1", "...", "A1", "..."], "default": "A1-B1"}
  ],
  "route": {
    "rules": [{"domain_suffix": [".ir"], "outbound": "direct"},
              {"ip_is_private": true, "outbound": "direct"}],
    "final": "route",
    "default_domain_resolver": "local"              // فقط modern
  },
  "dns": {"servers": [{"type": "local", "tag": "local"}]},   // فقط modern
  "experimental": {"clash_api": {"external_controller": "127.0.0.1:42816"}}
}
```

- **زنجیره** با فیلد `detour` ساخته می‌شود: outboundِ **B** با `detour = A`؛ یعنی اتصال به سرور B از داخل A برقرار می‌شود. نام زنجیره `"<tagA>-<tagB>"` است.
- **selector** `route` همه‌ی مسیرها را دارد؛ ترتیب فهرست برای ranking مهم نیست (ranking در Python نگه‌داری می‌شود)، فقط تعیین می‌کند چه گزینه‌هایی قابل انتخاب‌اند. سوییچ فقط یک `PUT /proxies/route` است، **بدون ری‌استارت** و فوری.
- `domain_suffix` / `ip_is_private`: بدون فیلد `action` معتبرند چون پیش‌فرض اکشن `route` است (در سورس sing-box تأیید شده).

### ۵.۲ modern در برابر legacy
هسته‌های ≥ 1.12 برای آدرس‌های دامنه‌ای نیاز به resolver صریح دارند؛ نبودنش از 1.12 deprecated و حذفش برای 1.14 برنامه‌ریزی شده (`OptionMissingDomainResolver`). بنابراین کانفیگ اول با بخش `dns` و `route.default_domain_resolver` ساخته می‌شود. هسته‌ی قدیمی‌تر این فیلدها را نمی‌شناسد و `check` رد می‌کند؛ آن‌گاه کانفیگ بدون این دو فیلد (legacy) امتحان می‌شود. با یک transport پیش‌فرض، رفتار بدون `dns` هنوز کار می‌کند.

### ۵.۳ رتبه‌بندی (`App.build_rank`)
- همه‌ی تگ‌ها (`k×k` زنجیره + `k` تکی B + `k` تکی A) با `Core.delay()` سنجیده می‌شوند: `GET /proxies/<tag>/delay` برای **هر** `check_urls`؛ اگر یکی شکست بخورد مسیر حذف می‌شود، وگرنه **میانگین** تاخیر ملاک است. موازی با ۸ رشته.
- ترتیب نهایی `rank`: **زنجیره‌ها** (تاخیر صعودی) ← **فقط B** ← **فقط A**.
- `idx` اندیس مسیر فعال در `rank` است (`-1` یعنی هیچ).

### ۵.۴ انتخاب و تأیید (`App.go`, `App.go_to`, `verify`)
`go(step)` از مسیر فعلی در جهت `step` (دوری) جلو می‌رود؛ برای هر کاندید:
1. `PUT /proxies/route` برای سوییچ،
2. `verify(cfg)`:
   - `GET <geo_url>` (پیش‌فرض `https://ipinfo.io/json`) از طریق پروکسی محلی؛ `geo_fallback_urls` هم‌زمان با آن پرسیده می‌شوند (اولین پاسخ معتبر برنده است، پس سرویس کند یا مسدود تأخیر نمی‌اندازد) (`parse_geo` فرمت ipinfo / country.is / ipwho.is را می‌فهمد). اگر `country ∈ blocked_countries` → رد. اگر هیچ‌کدام پاسخ ندهند، IP «unknown» است و **رد نمی‌شود**.
   - برای هر `strict_urls`: وضعیت `None` («no answer») یا `≥ 400` → رد. آدرس بدون scheme (`gemini.google.com`) هنگام بارگذاری به `https://...` تبدیل می‌شود (`normalize_url`)؛ قبلاً چنین مقداری همه‌ی مسیرها را رد می‌کرد.
   - برای `gemini.google.com`: صفحه می‌تواند 200 باشد ولی برنامه‌ی «Gemini در موقعیت شما پشتیبانی نمی‌شود» باشد، چون Google IP خروجی را در کشور دیگری (مثلاً IR) می‌بیند، حتی اگر ipinfo آن را DE نشان بدهد. `google_country()` کشوری را که Google خودش در صفحه گذاشته (`"XX","ZZ"` داخل `WIZ_global_data`، حدود ۱۳۵ کیلوبایت بعد از شروع صفحه؛ پس ۴۰۰ کیلوبایت خوانده می‌شود) می‌خواند و اگر در `blocked_countries` باشد مسیر را رد می‌کند. اگر مقدار پیدا نشد (Google فرمت را عوض کرده) رد نمی‌شود.
   - geo و strict_urls هم‌زمان اجرا می‌شوند؛ هر درخواست حداکثر `verify_timeout` ثانیه.

**ترتیب لیست:** پیش‌فرض (`rank_by_speed=false`) اول زنجیره‌های A→B، بعد فقط B، بعد فقط A؛ داخل هر گروه بر اساس سرعت. دلیل: هدف ابزار زنجیره است و زنجیره همیشه کندتر از اجزایش؛ ترتیب صرفاً سرعتی مسیرهای تک‌گره را بالا می‌آورد. با `rank_by_speed=true` ترتیب کاملاً سرعتی می‌شود.

**بسته‌شدن ناگهانی (kill / crash):**
- sing-box در یک Job Object ویندوز با `KILL_ON_JOB_CLOSE` اجرا می‌شود (`job_attach`)؛ با مرگ برنامه هسته هم می‌میرد و پورت را نگه نمی‌دارد.
- پس از تنظیم پروکسی، فرایند کوچک `chain.py guard <pid>` (`start_guard`) بالا می‌آید؛ اگر برنامه بدون `cleanup` بمیرد و `.proxy_state.json` مانده باشد، `sys_proxy_restore()` را اجرا می‌کند.
- باز کردن پنجره (`recover_after_crash`)، `Enable` و `chain.py off` هم در صورت وجود state قدیمی تنظیمات را برمی‌گردانند و هسته‌ی یتیم همین پوشه را (`kill_stale_core`) می‌کشند.
- پوشش‌داده‌نشده: خاموشی/Logoff ناگهانی (guard هم می‌میرد)؛ در لاگین بعدی با باز کردن برنامه یا `stop.bat` برمی‌گردد.
3. اولین تأییدشده فعال می‌ماند؛ اگر هیچ‌کدام نگذراند مسیر قبلی بازگردانده می‌شود.

همه‌ی تغییرها زیر `LOCK` (قفل بازگشتی سراسری) انجام می‌شوند تا کنسول/GUI/نگهبان/سوکت کنترل همزمان وضعیت را خراب نکنند.

---

## ۶. مدیریت هسته (sing-box)

### `find_core()`
ترتیب: متغیر محیطی `CHAIN_CORE` (برای تست) → `core/sing-box.exe` → `core/sing-box` → `PATH`.

### `ensure_core()` / `install_core(force)`
- هسته‌ی موجود با `sing-box version` سنجیده می‌شود؛ ناسالم → نصب مجدد.
- **منبع:** اگر `offline/sing-box*windows*.zip` باشد از آن (بدون شبکه) استفاده می‌شود. وگرنه `api.github.com/.../releases/latest`؛ اگر API در دسترس نبود، از ریدایرکت `/releases/latest` شماره‌ی نسخه گرفته و URL مستقیم ساخته می‌شود.
- **یکپارچگی:** اگر API فیلد `digest: sha256:...` بدهد، چک‌سام بایت‌های دانلودشده تطبیق داده می‌شود؛ ناسازگاری = خطا و **هیچ چیز نصب نمی‌شود**. (در مسیر ریدایرکت چک‌سامی در دسترس نیست؛ فقط خودآزمایی `version` انجام می‌شود.)
- **نصب اتمیک:** ابتدا در پوشه‌ی موقت داخل `core/` استخراج، بعد با `os.replace` جایگزین. فایل‌ها flatten می‌شوند (DLLهای همراه کنار exe می‌نشینند).
- دانلودها `http_get` با ۳ تلاش و عقب‌نشینی خطی دارند. اگر بررسی گواهی TLS در Python شکست بخورد (`CERTIFICATE_VERIFY_FAILED`، مثلاً «certificate has expired» روی ویندوزی با مخزن ریشه‌ی قدیمی یا زنجیره‌ی جدید Let's Encrypt)، بلافاصله `native_get` اجرا می‌شود: `curl.exe` ویندوز (schannel و مخزن گواهی ویندوز، مثل مرورگر و v2rayN) و در نبودش `Invoke-WebRequest`. **بررسی گواهی هرگز غیرفعال نمی‌شود.** خطاهای عادی شبکه به این مسیر نمی‌روند.

### `Core`
`start(conf)` کانفیگ را در `runtime/config.json` می‌نویسد، پردازش را بدون پنجره (`CREATE_NO_WINDOW`) اجرا می‌کند و تا آماده‌شدن Clash API منتظر می‌ماند. `restart(tag)`، `alive()`، `select(tag)`، `delay(tag,url,ms)`. تمام فراخوانی‌های Clash API با `NOPROXY` (opener بدون پروکسی) انجام می‌شود تا پس از تنظیم پروکسی سیستم، خودِ ابزار از پروکسی عبور نکند (حلقه). هندل لاگ در `stop()` بسته می‌شود.

---

## ۷. پروکسی ویندوز و چرخه‌ی عمر

### `sys_proxy_set(port, bypass)`
در `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`:
`ProxyEnable=1`، `ProxyServer=127.0.0.1:<port>`، `ProxyOverride=<bypass>` و حذف `AutoConfigURL` (یک PAC فعال، پروکسی دستی را باطل می‌کند). سپس `InternetSetOptionW(SETTINGS_CHANGED, REFRESH)`.

### حالت قبلی و بازگردانی
قبل از اولین دست‌کاری، مقدارهای اصلی `ProxyEnable/ProxyServer/ProxyOverride/AutoConfigURL` (با نوع رجیستری) در `.proxy_state.json` ذخیره می‌شود — **فقط اگر فایل وجود نداشته باشد**، تا بعد از کرش مقدار اصلی با مقدار ما بازنویسی نشود. `sys_proxy_restore()` آن‌ها را برمی‌گرداند (مقدار نبوده → حذف) و فایل را پاک می‌کند.

بازگردانی در این نقطه‌ها فراخوانی می‌شود: `App.cleanup()` (خروج عادی، دکمه Disable، بستن پنجره، `off`)، `atexit`، `SetConsoleCtrlHandler` (بستن پنجره‌ی کنسول)، شروع بعدی برنامه، و `chain.py off` وقتی برنامه در حال اجرا نیست.

### `App.cleanup()`
idempotent است (`cleaned`)، `stop_evt` را set می‌کند، سرور کنترل را می‌بندد، پروکسی ویندوز را برمی‌گرداند و هسته را متوقف می‌کند. GUI بعد از Disable یک `App` **جدید** با `start_session` می‌سازد.

---

## ۸. مرجع تنظیمات (`config.json`)

همه‌ی کلیدها اختیاری‌اند؛ مقدار پیش‌فرض از `DEFAULTS` در `chain.py` می‌آید.

| کلید | پیش‌فرض | توضیح |
|---|---|---|
| `mixed_port` | `42815` | پورت HTTP/SOCKS محلی (هدف پروکسی ویندوز). |
| `api_port` | `42816` | Clash API هسته (فقط `127.0.0.1`). |
| `control_port` | `42817` | سوکت کنترل برنامه (فقط `127.0.0.1`). |
| `top_k` | `5` | تعداد نودِ برگزیده‌ی ساپسکریپشن هاپ اول. |
| `top_k_exit` | `12` | تعداد نودِ برگزیده‌ی ساپسکریپشن هاپ آخر (بیشترشان مرده یا کندند، پس بیشتر امتحان می‌شود). تعداد زنجیره‌ها = (نودهای هاپ اول) × (نودهای هاپ آخر). |
| `tcp_timeout` | `3.0` | مهلت TCP probe (ثانیه). |
| `delay_timeout_ms` | `7000` | مهلت تست تاخیر هر مسیر. |
| `check_urls` | gstatic + cloudflare `generate_204` | آدرس‌های تست تاخیر؛ همه باید پاسخ دهند. |
| `strict_urls` | `["https://gemini.google.com"]` | آدرس‌هایی که باید با وضعیت `< 400` از مسیر عبور کنند. |
| `blocked_countries` | `["IR"]` | کشورهای ممنوع برای IP خروجی. |
| `direct_suffixes` | `[".ir"]` | دامنه‌هایی که مستقیم می‌روند. |
| `bypass` | شبکه‌های خصوصی + `<local>` | مقدار `ProxyOverride` ویندوز. |
| `watchdog_seconds` | `60` | بازه‌ی سنجش اتصال مسیر (۰ = خاموش). |
| `watchdog_failures` | `2` | شکست‌های پیاپی تا تعویض خودکار مسیر. |
| `log_level` | `"warn"` | سطح لاگ sing-box. |
| `geo_url` | `"https://ipinfo.io/json"` | سرویس تشخیص IP/کشور خروجی (پاسخ JSON با `ip`, `country`, `org`). خالی = بدون بررسی کشور. |
| `geo_fallback_urls` | `["https://api.country.is/", "https://ipwho.is/"]` | سرویس‌های جایگزین وقتی `geo_url` جواب ندهد. |
| `verify_timeout` | `12` | ثانیه برای هر درخواست تأیید مسیر. |
| `lantern_enabled` | `true` | هاپ اول، اولویت ۱: موتور Lantern. |
| `lantern_port` | `42819` | پورت SOCKS loopback موتور. |
| `lantern_timeout` | `90` | ثانیه‌ی انتظار برای آماده‌شدن Lantern؛ پس از آن بدون آن ادامه می‌دهد. |
| `top_k_profiles` | `3` | تعداد نود از هر فهرست پروفایل v2ray. |
| `auto_update` | `true` | نصب خودکار نسخه‌ی جدید (فقط نسخه‌ی نصب‌شده با نصب‌کننده). |
| `update_check_hours` | `6` | فاصله‌ی بررسی نسخه‌ی جدید. |
| `update_repo` | `"mhasgari/chainproxy-win"` | مخزن GitHub برای `releases/latest`. |
| `update_api` | `""` | جایگزین آدرس `releases/latest` (تست‌ها). |
| `update_first_check_seconds` | `45` | تاخیر اولین بررسی پس از باز شدن پنجره. |
| `close_to_tray` | `true` | بستن پنجره، برنامه را در tray نگه می‌دارد. |
| `gui_port` | `42818` | پورت loopback که پنجره را تک‌نمونه می‌کند. |
| `rank_by_speed` | `false` | `true` = ترتیب لیست فقط سرعتی (به‌جای زنجیره‌ها، بعد B، بعد A). |
| `private_direct` | `true` | مقصدهای خصوصی/LAN مستقیم بروند. آزمایشگاه e2e آن را `false` می‌کند. |

> فایل `config.json` همراه پروژه فقط چند کلید را صریح گذاشته؛ بقیه پیش‌فرض‌اند. GUI هنگام Save فقط `strict_urls`، `blocked_countries`، `direct_suffixes` را می‌نویسد و کلیدهای دیگر را دست‌نخورده نگه می‌دارد.

---

## ۹. نگهبان (`App.watchdog`)

حلقه‌ی ۵ ثانیه‌ای تا `stop_evt` فعال شود:

1. **زنده‌بودن هسته:** اگر `core.alive()` نیست → `Core.restart(tag_فعلی)` (هسته‌ی تازه با همان کانفیگ و انتخاب دوباره‌ی همان مسیر). اگر در ۵ دقیقه بیش از ۵ بار کرش کرد → `cleanup()` (پروکسی برمی‌گردد تا کاربر بی‌اینترنت نماند).
2. **سلامت مسیر** (هر `watchdog_seconds`): `GET check_urls[0]` از طریق پروکسی؛ بعد از `watchdog_failures` شکست پیاپی → `go(1)`.

> در محیط‌های تست بدون inbound واقعی، مرحله‌ی ۲ همیشه شکست می‌خورد (mock پروکسی ندارد)؛ آزمون‌ها `watchdog_seconds: 0` می‌گذارند.

---

## ۱۰. کنترل و رابط‌ها

### سوکت کنترل (`App.serve_control`)
`ThreadingTCPServer` روی `127.0.0.1:<control_port>`. پروتکل: یک خط فرمان → پاسخ متنی → بستن اتصال.

| فرمان | اثر |
|---|---|
| `next` / `prev` | `go(±1)` |
| `status` | مسیر فعال + IP خروجی |
| `list` | فهرست مرتب‌شده‌ی مسیرها |
| `rescan` | `build_rank` دوباره و `go(1)` |
| `off` | `stop_evt.set()` (خروج توسط حلقه‌ی اصلی/GUI) |

فرمان‌های خط فرمان: `chain.py` (کنسول تعاملی)، `chain.py serve` (بدون ورودی کنسول، برای خودکارسازی؛ با `off` یا SIGTERM تمام می‌شود)، `chain.py ensure` / `install-core` (هسته). `chain.py next|prev|status|list|rescan|off` فقط کلاینت همین سوکت‌اند (`control_send`). **احراز هویتی ندارد**؛ فرض بر این است که تمام کاربران محلیِ ماشین قابل‌اعتمادند.

### GUI (`gui.py`)
- عملیات سنگین در رشته‌ی پس‌زمینه (`run_bg`) و نتیجه با `queue` به رشته‌ی UI برمی‌گردد (`pump` هر ۳۰۰ms). tkinter هرگز از رشته‌ی دیگر لمس نمی‌شود.
- `chain.LOG_HOOK` هر خط `log()` را به کادر لاگ می‌رساند.
- `pump` تغییرهای ناشی از `next.bat/stop.bat` (`idx` و `stop_evt`) را دنبال می‌کند.
- اولین اجرا با `subs_are_placeholder()` پنجره‌ی Settings را باز می‌کند.
- خطاهای `start_session` (از جمله `SystemExit`) گرفته و در `messagebox` نشان داده می‌شوند.
- `gui.py --enable` پنجره را در حالت فعال باز می‌کند (برای تست خودکار یا اجرای خودکار با ویندوز).

---

## ۱۱. تست

چهار لایه، از سریع به کامل. جزئیات اجرا و راه‌اندازی محیط در [dev/README.md](../dev/README.md).

| لایه | فرمان | چه چیزی واقعی است |
|---|---|---|
| واحد | `make test` (`tests/run_tests.py`) | منطق Python؛ هسته ساختگی (`mock_core.py`) |
| GUI | `make test-gui` (`tests/gui_smoke.py`، زیر Xvfb) | پنجره‌ی tkinter؛ هسته ساختگی |
| e2e محلی | `make e2e-local` | **sing-box واقعی** در دو سر (کلاینت و نودهای A/B)؛ بدون ویندوز |
| VM ویندوز | `make vm-all` | ویندوز واقعی: `setup.ps1`، نصب Python، میانبرها، رجیستری، GUI روی دسکتاپ، sing-box ویندوزی |

### ۱۱.۱ آزمون‌های واحد
۳۸ آزمون بدون هسته‌ی واقعی، شبکه یا ویندوز. هر اجرا پروژه را در پوشه‌ی موقت کپی می‌کند، ساپسکریپشن نمونه می‌نویسد و `CHAIN_CORE` را به `tests/mock_core.py` می‌دهد (`core_cmd()` هسته‌ی `.py` را با همان Python اجرا می‌کند؛ روی ویندوز هم). پورت‌ها: `20808/20090/20091`.

| گروه | چه چیزی را می‌سنجد |
|---|---|
| `ParsingTests` | هر پروتکل/ترنسپورت، ورودی‌های خراب، base64 در برابر متن ساده، تشخیص لینک نمونه |
| `ConfigTests` | ساختار زنجیره (`detour`)، ترتیب selector، قوانین مسیر، `private_direct`، فقط‌لوکال‌بودن inbound، modern/legacy، اجرای هسته‌ی `.py` |
| `SessionTests` | جریان کامل: رتبه‌بندی (زنجیره ← B ← A)، حذف نود رد‌شده توسط هسته و مسیر شکست‌خورده، next/prev/go_to، سوکت کنترل، fallback به legacy، ری‌استارت هسته، خطای لینک نمونه |
| `RobustnessTests` | آدرس بدون scheme، فرمت پاسخ سرویس‌های geo و fallback، `rank_by_speed`، نگهبان (`guard`)، BOM، ساخت `subs.txt` از قالب، نبودن اشتراک کاربر در zip |
| `InstallerTests` | عدم تطابق چک‌سام، استخراج، fallback ریدایرکت، ترجیح بسته‌ی آفلاین (بدون شبکه) |

**رفتار `mock_core.py`:** `version` و `check` را پیاده می‌کند (رد `a3.test`؛ با `MOCK_OLD=1` رد `dns`)، و Clash API کمینه (`/version`, `/proxies/<tag>/delay`, `PUT /proxies/route`). تگ‌هایی که شامل `A2` باشند تاخیرشان شکست می‌خورد.

### ۱۱.۲ آزمایشگاه e2e (`dev/lab/`)
یک sing-box واقعی روی میزبان نقش پنج نود را بازی می‌کند (A1، A2، A3 مرده، B1، B2) و یک سرور HTTP نقش «اینترنت» را. کلاینت روی آدرس جعلی `198.51.100.10` تست می‌کند؛ نودها آن را به `127.0.0.1` بازنویسی و از آدرس loopback اختصاصی خودشان شماره‌گیری می‌کنند، پس سرور می‌داند درخواست از کدام نود خارج شده (B1 = `127.0.0.21`، کشور DE؛ B2 = کشور IR → ممنوع؛ خروجی‌های A → رد در `strict`).
انتظار: ۸ مسیر رتبه‌بندی‌شده، دقیقاً ۳ مسیر معتبر (A1-B1، A2-B1، B1)، همه‌ی ترافیک از B1. لاگ‌های خود نودها ثابت می‌کنند A به B1 وصل شده (زنجیره واقعاً برقرار بوده).
`dev/lab/e2e_client.py` همین جریان را از سمت کلاینت اجرا می‌کند و روی لینوکس (`make e2e-local`) و داخل VM (`make vm-e2e`) یکسان است؛ روی ویندوز رجیستری را هم بررسی می‌کند (مقادیر نگهبان، حذف PAC، بازگردانی دقیق).

### ۱۱.۳ VM ویندوز (`dev/vm/vmtest.py`)
مراحل: `deploy` → `install` (اجرای واقعی `setup.ps1`: Python، sing-box، میانبرها، اجرای دوم) → `unit` (همان آزمون‌های واحد روی ویندوز) → `e2e` (آزمایشگاه روی میزبان، کلاینت در VM) → `gui` (`gui_smoke.py` و پنجره‌ی واقعی روی دسکتاپ کاربر با اسکرین‌شات). خروجی‌ها در `dev/artifacts/vm-latest/`.

`make vm-installer` / `vm-installer-full` (با `--python full|notk`) نصب‌کننده‌ی ساخته‌شده را روی VM آزمایش می‌کنند: نصب، اجرای اول، ارتقا، حذف. `make vm-clean` VM را به حالت «بدون پروژه، Python و Inno Setup» برمی‌گرداند.

### آنچه هنوز پوشش داده نمی‌شود
- ساپسکریپشن‌ها و نودهای واقعی کاربر (پروتکل‌های غیر از shadowsocks فقط در آزمون‌های واحد و `sing-box check` سنجیده می‌شوند).
- ظاهر دقیق پنجره فقط با اسکرین‌شات بررسی می‌شود، نه به‌صورت خودکار.
- ویندوزهای غیرانگلیسی و حساب‌های Microsoft (VM آزمون با حساب محلی).

## ۱۲. توسعه‌ی ابزار

### افزودن پروتکل جدید
1. در `parse_node` شاخه‌ی طرح جدید را بگذارید که `(name, outbound)` برگرداند (فیلدها طبق مستندات [sing-box](https://sing-box.sagernet.org/configuration/outbound/)).
2. اگر UDP است، در `tcp_ms` مثل hysteria2 از TCP-probe معاف شود.
3. در `ParsingTests` یک آزمون بنویسید. `node_valid` به‌طور خودکار ناسازگاری با هسته را فیلتر می‌کند.

### تغییر معیار رتبه‌بندی
تنها نقطه‌ی تصمیم `App.build_rank` است (`measure_all` + مرتب‌سازی). برای مثال برای افزودن «سرعت دانلود»، یک سنجش اضافه به `measure_all` یا یک امتیاز ترکیبی به `ordered()` بدهید. معیارهای اعتبار (کشور، سایت‌های سخت‌گیر) در `verify` هستند، نه در رتبه‌بندی، چون نیاز به عبور واقعی ترافیک دارند.

### افزودن فرمان کنترل
یک شاخه در `App.handle`؛ CLI و سوکت خودکار پوشش می‌دهند (برای CLI نام را به لیست `main()` اضافه کنید)، و در GUI یک دکمه که `run_bg` را صدا بزند.

### قراردادها
- فقط کتابخانه‌ی استاندارد؛ هر وابستگی خارجی نیاز به توجیه دارد (راه‌انداز باید بدون `pip` کار کند).
- هر عملیات شبکه‌ی بیرونی: مهلت صریح و پیام خطای قابل‌فهم.
- هر تغییر در وضعیت پروکسی ویندوز باید راه بازگشت داشته باشد (`.proxy_state.json`).
- هیچ‌چیز نباید روی `0.0.0.0` گوش دهد.
- پیام‌های کنسول/GUI انگلیسی هستند (ناسازگاری کنسول ویندوز با متن راست‌به‌چپ)؛ مستندات فارسی‌اند.
- `setup.ps1` و فایل‌های `.bat` فقط ASCII و با انتهای خط CRLF باشند (PowerShell 5.1 فایل بدون BOM را ANSI می‌خواند).

### نسخه‌ی هسته و سازگاری
هسته‌ی «آخرین نسخه‌ی پایدار» نصب می‌شود. ناسازگاری‌های آینده (مثل حذف قابلیت‌های deprecated در 1.14) توسط `core_check` و fallback مدرن/legacy و `node_valid` به‌صورت امن مدیریت می‌شوند؛ اما اگر قالب بخش دیگری تغییر کرد، `build_config` را با `sing-box check` روی هسته‌ی جدید بازبینی کنید. برای پین‌کردن یک نسخه‌ی خاص، zip مربوطه را در `offline/` بگذارید.

---

## ۱۳. تصمیم‌های طراحی

| تصمیم | دلیل |
|---|---|
| یک selector + سوییچ با Clash API | سوییچ مسیر آنی، بدون قطع کامل اتصال‌ها و بدون ری‌استارت هسته |
| ساخت همه‌ی `k²` زنجیره و تست تاخیر داخل خود هسته | یک پردازش، تست واقعی مسیرِ دو‌هاپی (نه فقط هر هاپ جدا) |
| `verify` جدا از تاخیر | تاخیر پایین ≠ پذیرش سرویس؛ شرط‌های «کشور» و «سایت سخت‌گیر» فقط با ترافیک واقعی سنجیده می‌شوند |
| اعتبارسنجی تکی نود با `sing-box check` | یک نود بد، کل شروع را نمی‌شکند |
| فقط‌پروکسی‌سیستم (نه TUN) | نیازی به ادمین/درایور ندارد و ساده و قابل‌اتکا است؛ محدودیتش در راهنمای کاربر مستند است |
| ذخیره‌ی حالت اصلی پروکسی فقط یک‌بار | بعد از کرش، تنظیم اصلی کاربر گم نشود |
| پروکسی ویندوز فقط پس از یافتن مسیر سالم | کاربر هرگز به پروکسی مرده‌ی ما وصل نماند |
| Python بدون وابستگی + tkinter | نصب ساده، بدون `pip`، قابل اجرا حتی در شبکه‌ی محدود |
| نصب‌کننده‌ی Python با بررسی امضا، هسته با چک‌سام | اجرای فایل دانلودشده بدون راستی‌آزمایی پذیرفته نیست |
| میانبر فقط یک‌بار (و ترمیم مقصد) | حذف عمدی کاربر محترم شمرده می‌شود؛ جابه‌جایی پوشه خودترمیم است |

---

## ۱۴. محدودیت‌های شناخته‌شده و ایده‌ها

- پشتیبانی نشدن از Clash YAML / JSON sing-box / V2Ray JSON به‌عنوان ساپسکریپشن.
- عدم وجود kill switch و حالت TUN (روی ویندوز نیازمند ادمین/Wintun).
- رتبه‌بندی فقط بر پایه‌ی تاخیر؛ سرعت واقعی و پایداری سنجیده نمی‌شود.
- سوکت کنترل بدون احراز هویت (فقط لوکال).
- تشخیص کشور به یک سرویس خارجی (`ipinfo.io`) وابسته است؛ می‌توان چندین منبع یا پایگاه GeoIP محلی افزود.
- ایده‌ها: اجرا با شروع ویندوز، آیکون system tray، ذخیره‌ی «آخرین مسیر موفق»، امتیازدهی پایداری مسیر در طول زمان، به‌روزرسانی خودکار هسته.


---

## ۱۵. Lantern، منابع، tray و به‌روزرسانی (نسخه‌ی ۱.۳)

### ۱۵.۱ منابع و اولویت
`start_session` منابع را می‌خواند: `subscription_sources()` (خط ۱ و ۲ `subs.txt`؛ لینک `example.com/sub/` یعنی تنظیم‌نشده)، `load_profiles(FIRST_PROFILES|EXIT_PROFILES)` (فقط خط‌هایی که `parse_node` می‌فهمد)، و در صورت `lantern_enabled` یک `Lantern`. موتور در پس‌زمینه شروع می‌شود (`begin()`) و در این فاصله فهرست‌ها دانلود و `pick` می‌شوند. تگ‌ها: Lantern `A0`، ساپسکریپشن‌ها `A1..`/`B1..`، پروفایل‌ها `A101..`/`B101..`. `App.tier`: هاپ اول ۱ Lantern، ۲ ساپسکریپشن، ۳ پروفایل؛ هاپ آخر ۱ ساپسکریپشن، ۲ پروفایل. `build_rank` مسیرها را با کلید `(tier هاپ اول، tier هاپ آخر، تاخیر)` مرتب می‌کند (`rank_by_speed` = فقط تاخیر). `App.source_label` ستون Source را می‌سازد. اگر Lantern آماده نشود (`wait_ready`) فقط لاگ می‌شود و جلسه بدون آن ادامه می‌دهد؛ اگر موتور وسط کار بمیرد، `watchdog` تا ۵ بار در ۵ دقیقه دوباره راهش می‌اندازد. گره Lantern یک outbound از نوع `socks` به `127.0.0.1:lantern_port` است؛ گره‌های هاپ آخر با `detour` از آن عبور می‌کنند. (UDP مثل hysteria2 از SOCKS عبور نمی‌کند: چنین مسیری در تست تاخیر حذف می‌شود.)

### ۱۵.۲ موتور Lantern (`chainlantern`)
Lantern برنامه‌ی Flutter + هسته‌ی Go است (GPL-3.0). هسته‌ی آن `github.com/getlantern/radiance` است و `lanternd` آن سرویس سیستمی/TUN است که ادمین می‌خواهد و IPC آن روی pipe ثابت (HTTP/2 بدون TLS) و پورت‌نشده برای کلاینت ثالث است. راه‌حل: `dev/lantern/chainlantern/main.go` (حدود ۱۰۰ خط) داخل checkout سنجاق‌شده‌ی radiance با تگ **`novpn`** (ورودی mixed/SOCKS5 به‌جای TUN) ساخته می‌شود: `LocalBackend` را مستقیم می‌سازد، کاربر ناشناس می‌سازد، `ConnectVPN("auto")` می‌زند (انتخاب خودکار بهترین سرور رایگان) و روی stdout خط‌های `CHAINLANTERN READY|STATUS|ERROR` می‌نویسد؛ با بسته‌شدن stdin خارج می‌شود. بدون ادمین، بدون سرویس، بدون pipe (با Lantern نصب‌شده تداخل ندارد).
- ساخت: `python3 dev/build_lantern.py` (commit در خود اسکریپت سنجاق است؛ Go 1.26.x را خودش می‌گیرد؛ `CGO_ENABLED=0` برای ویندوز؛ zip قطعی با sha256 ثابت) ← `dist/engine/chainlantern-<commit>-windows-amd64.zip`.
- توزیع: zip به release با تگ `engine-<commit>` (pre-release تا «latest» به‌روزرسان نشود) آپلود می‌شود و sha256 آن در `LANTERN_ENGINE` (chain.py) ثابت است. `install_engine()` ابتدا `offline\chainlantern-*.zip` (نصب‌کننده‌ی Full) و بعد دانلود را می‌پذیرد و بسته‌ی با هش نامطابق را رد می‌کند.
- مجوز: GPL-3.0؛ zip شامل `LICENSE` و `SOURCE.txt`؛ `installer/THIRD-PARTY-NOTICES.txt` منبع و commit را می‌گوید. ارتقای radiance = commit جدید در `build_lantern.py` + آپلود + sha256 تازه + `make vm-lantern`.
- تست: `tests/mock_lantern.py` (همان پروتکل)، `make vm-lantern` (موتور واقعی روی VM ← زنجیره‌ی Lantern→GeminiRoute، IP خروجی، gemini ۲۰۰، توقف با جلسه).

### ۱۵.۳ tray، آیکون، تک‌نمونه
- `tray.py`: `Tray(icon, tip, on_command, get_menu, on_endsession)`. منو با `TrackPopupMenu(TPM_RETURNCMD)`؛ `on_command` فقط در صف GUI می‌گذارد. `WM_ENDSESSION` ← پروکسی بازگردانده می‌شود (Logoff/Shutdown). اگر tray نبود، بستن پنجره خروج است.
- **آیکون:** در پنجره **فقط** `iconphoto(True, PNGها)`؛ استفاده‌ی هم‌زمان از `iconbitmap(default=ico)` روی Windows 11 / Tk 8.6.15 لوگوی Python را در taskbar و نوار عنوان می‌آورد (با اسکرین‌شات ثابت شد). `SetCurrentProcessExplicitAppUserModelID("mhasgari.ChainProxy")` و `AppUserModelID` میانبرهای Inno باعث می‌شود اعلان‌ها «Chain Proxy» بگویند نه «Python». `chainproxy.ico` قبلاً فقط یک PNG ۲۵۶ بود؛ اکنون ۱۰ اندازه (BMP برای ≤۱۲۸ و PNG برای ۲۵۶، `dev/make_icons.py`).
- تک‌نمونه: `gui.single_instance(gui_port)`؛ نمونه‌ی دوم به اولی `show` می‌فرستد.

### ۱۵.۴ به‌روزرسانی خودکار
`latest_release` (`api.github.com/.../releases/latest`، فقط تگ `vX.Y.Z`) ← `update_available` ← `download_update` (asset `ChainProxy-Setup-X.Y.Z.exe`؛ **sha256 از `digest` متادیتای GitHub** اجباری است، بدون آن فقط اعلان) ← `apply_update` (نصب‌کننده با `/VERYSILENT /LAUNCH=1` جدا از فرایند؛ نشانه‌ی `.resume_enabled` اگر فعال بود) ← برنامه خارج می‌شود. نصب‌کننده `quit.bat` را اجرا می‌کند، فایل‌ها را عوض می‌کند و با `/LAUNCH=1` برنامه را باز می‌کند؛ پنجره‌ی تازه `.resume_enabled` را می‌بیند و دوباره Enable می‌کند. `subs.txt`، `config.json`، `profiles_*.txt` دست‌نخورده می‌مانند. نسخه‌ی portable (بدون `unins000.exe`) فقط اعلان می‌دهد. امنیت: هش و فایل هر دو از GitHub می‌آیند؛ در برابر خرابی محافظت می‌کند، نه در برابر نفوذ به حساب GitHub؛ نصب‌کننده امضای دیجیتال ندارد.
- تست: واحد (`test_update_check_and_download`) و `make vm-update` (نصب‌کننده‌ی جاری + release جعلی `9.9.9` روی سرور HTTP میزبان ← خودبه‌روزرسانی، یک پنجره بعد از آن، حفظ داده، بسته‌شدن پنجره‌ی tray توسط حذف‌کننده).
