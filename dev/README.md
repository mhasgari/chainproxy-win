# محیط توسعه روی CachyOS و تست خودکار روی VM ویندوز

این راهنما برای ادامه‌ی توسعه‌ی پروژه با **Claude Code** روی **CachyOS** (یا هر توزیع Arch) و تست خودکار آن روی یک **ماشین مجازی ویندوز در virt-manager** است. معماری و منطق برنامه در [docs/DEVELOPER.md](../docs/DEVELOPER.md) آمده است.

---

## ۱. چه چیزی کجا اجرا می‌شود

```
 CachyOS (میزبان)                                         VM ویندوز (libvirt / NAT default)
 ┌───────────────────────────────────────────┐           ┌──────────────────────────────────┐
 │ Claude Code ── make ── dev/vm/vmtest.py ───┼── ssh ───►│ OpenSSH Server (کلید اختصاصی)    │
 │                          │      │          │  scp      │ ~\chainproxy-test\repo            │
 │                          │      └ virsh ───┼──────────►│  (اسکرین‌شات، snapshot، agent)    │
 │ dev/lab/lab.py:                            │           │                                  │
 │   sing-box واقعی = نودهای A1 A2 B1 B2  ◄───┼── ss ─────┤ chain.py + sing-box.exe          │
 │   HTTP = «اینترنت» جعلی + ساپسکریپشن‌ها ◄──┼── http ───┤ e2e_client.py / gui.py           │
 │   (روی 192.168.122.1)                      │           │                                  │
 └───────────────────────────────────────────┘           └──────────────────────────────────┘
```

- همه‌چیز از میزبان کنترل می‌شود؛ داخل ویندوز فقط یک بار راه‌اندازی اولیه لازم است.
- ارتباط: **SSH با کلید اختصاصی** (`dev/vm/.ssh/`). هر فرمان در ویندوز به‌صورت `powershell -EncodedCommand` اجرا می‌شود تا مشکل نقل‌قول پیش نیاید.
- تست‌ها **هرمتیک** هستند: نودهای «A» و «B» روی خود میزبان با sing-box واقعی اجرا می‌شوند. به ساپسکریپشن‌های واقعی یا اینترنت آزاد نیازی نیست. فقط برای دریافت یک‌باره‌ی نصب‌کننده‌ها به اینترنت نیاز دارید.

---

## ۲. پیش‌نیازها

- CachyOS با دسترسی sudo
- یک VM ویندوز ۱۰ یا ۱۱ در virt-manager:
  - با یک **حساب محلی** (نه حساب Microsoft) با دسترسی Administrator
  - روی شبکه‌ی NAT پیش‌فرض libvirt (`default`، میزبان = `192.168.122.1`)
  - توصیه می‌شود: نصب **virtio-win guest tools** (شامل QEMU guest agent) تا راه‌اندازی اولیه کاملاً خودکار شود
- Claude Code روی میزبان ([راهنمای نصب](https://docs.claude.com/en/docs/claude-code/setup))

---

## ۳. راه‌اندازی یک‌باره

### ۳.۱ پروژه و بسته‌ها
```bash
unzip chainproxy-dev.zip -d ~/Projects && cd ~/Projects/chainproxy
bash dev/setup-cachyos.sh
```
این اسکریپت بسته‌ها را نصب می‌کند: python، tk، xvfb، openssh، libvirt، qemu، virt-manager، sing-box و pyflakes. کاربر را به گروه `libvirt` اضافه می‌کند، شبکه‌ی `default` را فعال می‌کند و مخزن git را می‌سازد (بدون commit). `dev/vm/vm.conf` را هم ایجاد می‌کند.
اگر به گروه `libvirt` اضافه شدید، یک بار **logout/login** کنید.

> sing-box مخزن Arch باید `with_clash_api` داشته باشد (اسکریپت بررسی می‌کند). اگر نداشت، نسخه‌ی رسمی را خودکار در `dev/bin/` می‌گذارد. با `--official-singbox` این کار اجباری می‌شود.

### ۳.۲ تنظیم VM
در `dev/vm/vm.conf` دست‌کم این دو را بنویسید:
```ini
VM_NAME=win11        # نام VM در virt-manager  (virsh -c qemu:///system list --all)
WIN_USER=tester      # نام حساب ویندوزی داخل VM
```

### ۳.۳ دریافت نصب‌کننده‌ها (یک بار)
```bash
make vm-fetch
```
این فرمان نصب‌کننده‌ی Python و sing-box ویندوزی (با تأیید sha256) و MSI سرور OpenSSH (اختیاری) را در `dev/vm/cache/` می‌گذارد. در هر deploy همین‌ها در پوشه‌ی `offline\` پروژه داخل VM قرار می‌گیرند. یعنی VM برای تست‌ها **به اینترنت نیاز ندارد** و مسیر آفلاین برنامه هم تست می‌شود.
اگر دانلود از شبکه‌ی شما ممکن نیست، همین فایل‌ها را دستی در `dev/vm/cache/` بگذارید.

### ۳.۴ SSH داخل VM (یک بار)
```bash
make vm-bootstrap                      # یا: python3 dev/vm/vmtest.py bootstrap --autologon
```
- **اگر guest agent نصب است:** همه‌چیز خودکار انجام می‌شود.
- **اگر نیست:** یک فرمان یک‌خطی چاپ می‌شود. آن را در VM در یک **PowerShell با Run as administrator** وارد کنید. میزبان منتظر می‌ماند تا SSH بالا بیاید.

این مرحله OpenSSH Server را نصب می‌کند (اول از قابلیت ویندوز، و اگر نشد از MSI دریافت‌شده). قانون فایروال و کلید میزبان را اضافه می‌کند و Sleep و Hibernate را خاموش می‌کند.
`--autologon` ورود خودکار کاربر را فعال می‌کند. این برای **تست GUI** لازم است، چون پنجره باید روی دسکتاپِ کاربرِ واردشده باز شود. بعد از آن یک بار VM را ری‌استارت کنید.

### ۳.۵ snapshot پایه (اختیاری ولی توصیه‌شده)
```bash
make vm-snapshot
```
`make vm-all-clean` قبل از هر اجرا به این snapshot برمی‌گردد. اگر snapshot در وضعیت «بدون Python» گرفته شود، **اولین نصب کامل** (`Run.bat` روی ماشین تمیز) هر بار تست می‌شود.
VMهای UEFI (ویندوز ۱۱) گاهی snapshot کامل نمی‌پذیرند. اسکریپت در این حالت snapshot دیسکی را امتحان می‌کند. اگر آن هم نشد، از virt-manager snapshot بگیرید یا بدون `--clean` کار کنید.

### ۳.۶ بررسی نهایی
```bash
make vm-doctor
```
هر مورد ناموفق همراه با فرمان رفعش نمایش داده می‌شود: ابزارها، دسترسی libvirt، وضعیت VM، SSH، **رسیدن ترافیک VM به میزبان** (فایروال)، کش و snapshot.

---

## ۴. کار با Claude Code

```bash
cd ~/Projects/chainproxy
git add -A && git commit -m "Import chainproxy"   # اولین commit (اختیاری ولی مفید)
claude
```
- **`CLAUDE.md`** به Claude می‌گوید پروژه چیست، کدام تست کجا اجرا شود، قواعد (فقط کتابخانه‌ی استاندارد، ASCII و CRLF برای اسکریپت‌های ویندوز، پاسخ فارسی و کد انگلیسی) و نکات VM.
- **`.claude/settings.json`** دسترسی‌ها را تعیین می‌کند:
  - **بدون پرسش:** فرمان‌های تست و VM.
  - **با پرسش:** `revert`، `snapshot`، `commit`، `push`.
  - **ممنوع:** خواندن کلید SSH و `vm.conf`، `sudo`، و حذف VM یا snapshot.
  
  تنظیمات شخصی را در `.claude/settings.local.json` بگذارید (در git نمی‌رود).
- **فرمان‌های آماده:**
  - `/check`: همه‌ی تست‌های بدون VM
  - `/vm-test [all|install|unit|e2e|gui]`: اجرا روی VM و تحلیل لاگ‌ها و اسکرین‌شات‌ها
  - `/release [نسخه]`: تست کامل و ساخت zip

جریان کار پیشنهادی: تغییر بدهید ← `make test` ← اگر کانفیگ sing-box عوض شده `make e2e-local` ← اگر رفتار ویندوزی عوض شده `make vm-all` (یا فقط مرحله‌ی مربوط).

---

## ۵. فرمان‌ها

| فرمان | کار | زمان تقریبی |
|---|---|---|
| `make test` | آزمون‌های واحد (هسته‌ی ساختگی) | ~۱۰ ثانیه |
| `make test-gui` | تست پنجره زیر Xvfb | ~۱۰ ثانیه |
| `make test-dev` | تست ابزارهای توسعه (lab، vmtest) | ~۲ ثانیه |
| `make lint` | کامپایل، pyflakes، قواعد ASCII/CRLF | ~۲ ثانیه |
| `make e2e-local` | زنجیره با **sing-box واقعی** روی همین لینوکس | ~۳۰ ثانیه |
| `make check` | همه‌ی موارد بالا | ~۱ دقیقه |
| `make vm-install` | deploy و اجرای واقعی `setup.ps1` (Python، sing-box، میانبرها، اجرای دوم) | ۱ تا ۵ دقیقه |
| `make vm-unit` | آزمون‌های واحد روی ویندوز | ~۳۰ ثانیه |
| `make vm-e2e` | زنجیره‌ی واقعی در ویندوز در برابر آزمایشگاه میزبان، همراه با رجیستری | ~۲ دقیقه |
| `make vm-gui` | تست پنجره روی دسکتاپ و پنجره‌ی واقعی با اسکرین‌شات | ~۲ دقیقه |
| `make vm-all` | deploy، install، unit، e2e و gui | ۵ تا ۱۰ دقیقه |
| `make vm-all-clean` | همان، پس از بازگشت به snapshot | +۱ تا ۳ دقیقه |
| `make vm-shell` | PowerShell تعاملی داخل VM | |
| `make vm-screenshot`, `make vm-logs` | اسکرین‌شات و لاگ‌های VM | |
| `make package` | zip نسخه‌ی کاربر در `dist/` | |
| `make pdf` | ساخت PDF راهنمای سریع از `docs/QUICKSTART.md` (pandoc + chromium روی میزبان) | چند ثانیه |
| `make installer` | ساخت دو نصب‌کننده‌ی `dist/ChainProxy-Setup-<ver>.exe` و `...-Full-...` با Inno Setup **داخل VM** (اگر نباشد با بررسی امضا خودش نصب می‌شود) | ~۲ دقیقه |
| `make vm-installer` / `make vm-installer-full` (و `python3 dev/vm/vmtest.py installer --full --python full\|notk` برای «Python از قبل هست / بدون tkinter») | آزمون نصب‌کننده در VM: نصب، اجرای اول (`setup.ps1`، Python، sing-box)، ارتقا (حفظ `subs.txt`)، حذف | ۱ تا ۳ دقیقه |
| `make lantern` | ساخت موتور Lantern (`dist/engine/chainlantern-<commit>-windows-amd64.zip`) از commit سنجاق‌شده‌ی radiance با Go (روی میزبان؛ بدون کامپایلر C برای ویندوز) | ~۱ تا ۴ دقیقه |
| `make vm-lantern` | موتور واقعی روی VM: زنجیره‌ی Lantern→لیست GeminiRoute، IP خروجی، gemini، توقف با جلسه (اینترنت لازم است) | ~۲ دقیقه |
| `make vm-update` | آزمون به‌روزرسانی خودکار: نصب‌کننده‌ی جاری + release جعلی `9.9.9` روی سرور HTTP میزبان | ~۲ دقیقه |
| `make vm-clean` | **همه‌ی آثار پروژه را از VM پاک می‌کند** (کپی تست، برنامه‌ی نصب‌شده، نصب‌کننده‌ها، میانبرها، Python و Inno Setup، تنظیم پروکسی). OpenSSH/sshd، کلید، autologon و کاربر دست‌نخورده می‌مانند | ~۱ دقیقه |
| `make vm-clean-light` | همان ولی Python و Inno Setup می‌مانند (چرخه‌ی سریع‌تر) | ~۳۰ ثانیه |

گزینه‌های `vmtest.py`:
- `--online`: نصب‌کننده‌ها را نفرست تا VM خودش دانلود کند.
- `--no-deploy`: همان نسخه‌ی موجود در VM را تست کن.
- `--skip-gui`
- `all --clean`

هر تنظیم `vm.conf` را می‌توان با متغیر محیطی جایگزین کرد، مثلاً `VM_NAME=win10 make vm-all`.

### حلقه‌ی توسعه و تست سریع
روی میزبان کد را عوض کنید و:
1. `make test` (۱۰ ثانیه) و برای کار روی config یا پنجره `make check`.
2. چیزهایی که فقط روی ویندوز معنا دارند: `make vm-deploy vm-unit` (~۱ دقیقه)، یا مرحله‌ی مربوطه (`vm-gui`، `vm-e2e`). `vm-deploy` هر بار کل درخت کار را می‌فرستد و `chain.py off` و فرایندهای قبلی را می‌بندد.
3. پیش از انتشار: `make vm-all`، بعد `make pdf package installer`، `make vm-installer vm-installer-full` (روی VM تمیز: اول `make vm-clean`).
4. تست نصب از صفر (مثل کاربر): `make vm-clean` ← `make vm-installer-full` (یا `vm-installer`، که Python و sing-box را از اینترنت می‌گیرد). بعد از آن دوباره `make vm-clean` تا VM تمیز بماند.

برای تست دستی با اشتراک‌های واقعی: `make vm-deploy` (فایل `subs.txt` میزبان همراه می‌رود؛ `vm-all` آن را با لینک‌های lab بازنویسی می‌کند)، سپس `python3 dev/vm/vmtest.py ps "..."` یا `make vm-shell`.

### خروجی‌ها
`dev/artifacts/vm-latest/` به آخرین اجرا اشاره دارد و این فایل‌ها را دارد:
- `summary.json`: نتیجه‌ی هر مرحله
- `install.log`، `unit.log`، `e2e.log`، `gui.log`
- `e2e-core.log` و `e2e-config.json`: لاگ و کانفیگ sing-box داخل VM
- `lab/lab-singbox.log` و `lab-evidence.json`: شواهد زنجیره از دید نودها
- `gui-1-active.png`، `gui-2-next.png`، `gui-3-disabled.png`

---

## ۶. آزمایشگاه e2e در یک نگاه

| نود | نقش | نتیجه‌ی مورد انتظار |
|---|---|---|
| A1، A2 | هاپ اول | در زنجیره استفاده می‌شوند. مسیر «فقط A» در `strict` رد می‌شود |
| A3 | پورت بسته | باید حذف شود |
| B1 | خروجی، کشور DE | **همه‌ی ترافیک از اینجا خارج می‌شود** |
| B2 | خروجی، کشور IR | به‌خاطر `blocked_countries` رد می‌شود |

- از ۸ مسیر رتبه‌بندی‌شده دقیقاً ۳ مسیر معتبر است: A1→B1، A2→B1 و B1.
- `next` باید بین همین سه بچرخد.
- لاگ خودِ نودها نشان می‌دهد A واقعاً به B1 وصل شده است.

اجرای دستی برای بررسی:
```bash
python3 dev/lab/lab.py --listen 192.168.122.1    # Ctrl+C برای توقف
```

---

## ۷. عیب‌یابی

| مشکل | راه‌حل |
|---|---|
| `access to qemu:///system` ناموفق | `sudo usermod -aG libvirt $USER` و logout/login؛ `sudo systemctl enable --now libvirtd.socket` |
| VM آدرس IP ندارد | VM روشن و روی شبکه‌ی `default` باشد. guest agent کمک می‌کند. در غیر این صورت `VM_IP` را در `vm.conf` بنویسید |
| bootstrap: دانلود اسکریپت در VM گیر می‌کند | فایروال میزبان پورت `BOOT_PORT` را بسته است (ردیف بعد را ببینید) |
| `VM -> host ... blocked` در doctor | ufw: `sudo ufw allow in on virbr0`<br>firewalld: `sudo firewall-cmd --permanent --zone=libvirt --add-port=18000-18999/tcp && sudo firewall-cmd --reload` |
| نصب OpenSSH در VM خیلی طول می‌کشد یا خطا می‌دهد | قابلیت ویندوز به Windows Update وابسته است. `make vm-fetch` (MSI) و دوباره `make vm-bootstrap` |
| `ssh` با کلید کار نمی‌کند | دوباره `make vm-bootstrap` (تکرارپذیر است). در VM: `Get-Service sshd` |
| مرحله‌ی gui با SKIP رد می‌شود | کسی وارد دسکتاپ VM نشده است. وارد شوید، یا `bootstrap --autologon` و ری‌استارت |
| اسکرین‌شات‌ها صفحه‌ی قفل را نشان می‌دهند | قفل خودکار ویندوز را در VM خاموش کنید (Settings ← Accounts ← Sign-in options) |
| `sing-box ... lacks with_clash_api` | `bash dev/setup-cachyos.sh --official-singbox` |
| `lab ports already in use` | پورت‌ها را در `vm.conf` (`LAB_PORT`، `NODE_PORT_BASE`) تغییر دهید |
| snapshot ساخته نمی‌شود | ویندوز ۱۱ با UEFI: از virt-manager snapshot بگیرید یا بدون `--clean` کار کنید |
| `bootstrap`: `guest-exec ... Permission denied` | agent داخل VM اجازه‌ی اجرای برنامه نمی‌دهد. ابزار خودکار به حالت دستی می‌رود: فرمان چاپ‌شده را یک بار در PowerShell مدیر داخل VM بزنید (در حالی که `make` منتظر است) |
| `remote username contains invalid characters` | نام کاربر دامنه‌ای `DOMAIN\user` است. ابزار آن را خودکار به `user@DOMAIN` تبدیل می‌کند. دستی: `ssh user@DOMAIN@IP` |
| `VM port 22 open` ناموفق ولی `nc` به آدرس libvirt موفق است | VM دو کارت شبکه دارد و آدرس غلط انتخاب شده. نسخه‌ی فعلی آدرس زیرشبکه‌ی libvirt را ترجیح می‌دهد. وگرنه `VM_IP` را بنویسید |
| `all --clean` به snapshot برنمی‌گردد | snapshot خارجی (UEFI) با `snapshot-revert` برگشت‌پذیر نیست. بدون `--clean` اجرا کنید یا از virt-manager clone بگیرید |
| `deploy failed` | فایلی در پوشه‌ی تست قفل است. `make vm-shell` و بستن پنجره‌ی برنامه، یا ری‌استارت VM |
| پروکسی دسکتاپ شما در تست محلی دخالت می‌کند | `e2e-local` متغیرهای `*_proxy` را برای کلاینت حذف می‌کند. اگر sing-box میزبان را خودتان با TUN اجرا می‌کنید، موقتاً متوقفش کنید |

---

## ۸. امنیت

- VM آزمون را **دورریختنی** بدانید. تست‌ها رجیستری پروکسی کاربر آن را تغییر می‌دهند و بعد برمی‌گردانند، و Python و میانبر نصب می‌کنند.
- کلید SSH فقط در `dev/vm/.ssh/` است و در git نمی‌رود. Claude Code اجازه‌ی خواندن آن را ندارد.
- رمز `--autologon` به‌صورت متن ساده در رجیستری VM ذخیره می‌شود (روش استاندارد autologon ویندوز). فقط برای VM آزمون از آن استفاده کنید.
- سرور HTTP راه‌اندازی اولیه فقط در طول `bootstrap` و فقط روی آدرس شبکه‌ی libvirt باز است. پورت‌های آزمایشگاه هم فقط در طول تست و فقط روی همان آدرس و `127.0.0.1` باز هستند.

---

## ۹. ساختار `dev/`

```
dev/
├── README.md                  این راهنما
├── setup-cachyos.sh           راه‌اندازی میزبان
├── package.py                 zip کاربر نهایی + بررسی قواعد اسکریپت‌های ویندوز
├── make_pdf.py                PDF راهنمای سریع از docs/QUICKSTART.md (pandoc + chromium)
├── make_installer.py          نصب‌کننده‌های Inno Setup (داخل VM ساخته می‌شوند)
├── lab/
│   ├── lab.py                 نودهای A/B با sing-box واقعی + «اینترنت» جعلی
│   ├── e2e_client.py          جریان آزمون از سمت کلاینت (لینوکس یا ویندوز)
│   └── e2e_local.py           e2e روی خود میزبان
├── vm/
│   ├── vmtest.py              راننده‌ی VM (همه‌ی فرمان‌های make vm-*)
│   ├── vm.conf.example        نمونه‌ی تنظیمات  →  vm.conf (محلی)
│   └── guest/                 اسکریپت‌هایی که داخل ویندوز اجرا می‌شوند
│       ├── bootstrap.ps1      SSH + کلید + autologon (یک بار)
│       ├── common.ps1         توابع مشترک (یافتن Python، اجرا روی دسکتاپ، ...)
│       ├── install.ps1        آزمون نصب اولیه
│       ├── installer-test.ps1 آزمون نصب‌کننده (نصب، اجرای اول، ارتقا، حذف)
│       └── clean.ps1          برگرداندن VM به حالت بدون پروژه (make vm-clean)
└── tests/test_devtools.py     آزمون خود این ابزارها
```
پوشه‌های محلی که در git نمی‌روند: `dev/vm/.ssh/`، `dev/vm/cache/`، `dev/artifacts/`، `dev/bin/`.
