# chainproxy developer commands (Linux host). `make help` lists them.
PY      ?= python3
VMTEST  := $(PY) dev/vm/vmtest.py
XVFB    := $(shell command -v xvfb-run 2>/dev/null)

.DEFAULT_GOAL := help
.PHONY: android-test android-apk android-emu-test help test test-gui test-dev lint check e2e-local package pdf installer clean \
        vm-doctor vm-fetch vm-bootstrap vm-snapshot vm-revert vm-deploy vm-install \
        vm-unit vm-e2e vm-gui vm-lantern vm-update lantern vm-clean vm-clean-light vm-installer vm-installer-full vm-all vm-all-clean vm-shell vm-screenshot vm-logs

help:                ## show this help
	@grep -hE '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | expand -t 18

# ---------------------------------------------------------------- local (no VM)
test:                ## unit tests (mock core, no network)
	$(PY) tests/run_tests.py

test-gui:            ## GUI smoke test under Xvfb
ifdef XVFB
	xvfb-run -a $(PY) tests/gui_smoke.py
else
	$(PY) tests/gui_smoke.py
endif

test-dev:            ## tests for the dev tooling (vmtest, lab)
	$(PY) dev/tests/test_devtools.py

lint:                ## syntax + pyflakes + ASCII/CRLF rules for Windows scripts
	$(PY) -m py_compile chain.py gui.py tests/*.py dev/lab/*.py dev/vm/*.py dev/tests/*.py dev/*.py
	-$(PY) -m pyflakes chain.py gui.py tests dev 2>/dev/null || true
	$(PY) dev/package.py --check

e2e-local:           ## end-to-end with the REAL sing-box on this machine
	$(PY) dev/lab/e2e_local.py

check: lint test test-dev test-gui e2e-local   ## everything that runs without the VM

pdf:                 ## rebuild docs/Chain-Proxy-Quick-Start-fa.pdf (pandoc + chromium)
	$(PY) dev/make_pdf.py

installer:           ## build dist/ChainProxy-Setup-<ver>.exe and the -Full one (with Python + sing-box) in the VM
	$(PY) dev/make_installer.py
	$(PY) dev/make_installer.py --full

package:             ## release zip in dist/
	$(PY) dev/package.py

clean:               ## remove caches and local run state (keeps dev/vm/cache)
	rm -rf __pycache__ */__pycache__ */*/__pycache__ cache runtime core dist .proxy_state.json

# ---------------------------------------------------------------- Windows VM
vm-doctor:           ## check host, libvirt, VM, ssh, firewall
	$(VMTEST) doctor
vm-fetch:            ## download installers for the VM into dev/vm/cache
	$(VMTEST) fetch
vm-bootstrap:        ## one-time: OpenSSH + key in the VM
	$(VMTEST) bootstrap
vm-snapshot:         ## snapshot the prepared VM
	$(VMTEST) snapshot
vm-revert:           ## back to the snapshot
	$(VMTEST) revert
vm-deploy:           ## copy the working tree into the VM
	$(VMTEST) deploy
vm-install:          ## first-run test (setup.ps1, Python, sing-box, shortcuts)
	$(VMTEST) install
vm-unit:             ## unit tests on Windows
	$(VMTEST) unit
vm-e2e:              ## real chain against the host lab + registry checks
	$(VMTEST) e2e
vm-gui:              ## GUI on the VM desktop + screenshots
	$(VMTEST) gui
vm-lantern:          ## real Lantern engine -> chain with the GeminiRoute exit list (needs the internet)
	$(VMTEST) lantern

vm-update:           ## self-update test: installer -> fake newer release on a host server -> app updates itself
	$(VMTEST) update

lantern:             ## build the Lantern engine zip (dist/engine/) from the pinned radiance commit
	$(PY) dev/build_lantern.py

vm-clean:            ## remove EVERYTHING the project put into the VM (Python, Inno Setup too)
	$(VMTEST) clean

vm-clean-light:      ## same, but keep Python and Inno Setup
	$(VMTEST) clean --keep-tools

vm-installer:        ## test dist/ChainProxy-Setup-<ver>.exe in the VM (first run, upgrade, uninstall)
	$(VMTEST) installer

vm-installer-full:   ## test the Full installer (Python + sing-box inside)
	$(VMTEST) installer --full

vm-all:              ## deploy, install, unit, e2e, gui
	$(VMTEST) all
vm-all-clean:        ## same, starting from the clean snapshot
	$(VMTEST) all --clean
vm-shell:            ## PowerShell in the VM
	$(VMTEST) shell
vm-screenshot:       ## save the VM screen
	$(VMTEST) screenshot
vm-logs:             ## copy runtime logs out of the VM
	$(VMTEST) pull-logs

android-test:        ## Android: JVM unit tests (golden vectors from chain.py: python3 dev/android/gen_golden.py)
	dev/android/gradlew.sh :app:testDebugUnitTest
android-apk:         ## Android: signed release APK -> dist/ChainProxy-<version>.apk
	dev/android/make_apk.sh
android-emu-test:    ## Android: debug APK on the emulator + lab session test (emulator must run: dev/android/emu.sh start)
	dev/android/gradlew.sh :app:assembleDebug
	. dev/android/env.sh && adb install -r android/app/build/outputs/apk/debug/app-x86_64-debug.apk
	. dev/android/env.sh && python3 dev/android/emu_session_test.py
	. dev/android/env.sh && python3 dev/android/emu_vpn_test.py
