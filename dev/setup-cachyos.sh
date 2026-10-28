#!/usr/bin/env bash
# One-time developer setup on CachyOS / Arch Linux.
#
#   dev/setup-cachyos.sh                    packages, libvirt access, sing-box, git, vm.conf
#   dev/setup-cachyos.sh --official-singbox also put the official sing-box release in dev/bin
#                                           (when the distro build lacks with_clash_api)
#   dev/setup-cachyos.sh --no-packages      skip pacman (already installed)
#
# Safe to run again. Uses sudo only for pacman, systemctl and usermod.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OFFICIAL_SINGBOX=0
PACKAGES=1
for arg in "$@"; do
  case "$arg" in
    --official-singbox) OFFICIAL_SINGBOX=1 ;;
    --no-packages) PACKAGES=0 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m  %s\n' "$*"; }
warn() { printf '  \033[33m!!\033[0m  %s\n' "$*"; }

if [[ $EUID -eq 0 ]]; then
  echo "run this as your normal user (it calls sudo where needed)" >&2
  exit 1
fi

# --------------------------------------------------------------------------- packages
if [[ $PACKAGES -eq 1 ]]; then
  say "installing packages (pacman)"
  PKGS=(
    git make python tk                      # app + tests (tkinter)
    xorg-server-xvfb                        # headless GUI test
    openssh                                 # talking to the VM
    libvirt qemu-desktop virt-manager dnsmasq edk2-ovmf swtpm   # VM host (Windows 11: UEFI + TPM)
    sing-box                                # real core for the e2e lab
    python-pyflakes                         # make lint
  )
  missing=()
  for p in "${PKGS[@]}"; do pacman -Si "$p" &>/dev/null || missing+=("$p"); done
  if ((${#missing[@]})); then
    warn "not in your repositories (skipped): ${missing[*]}"
  fi
  install=()
  for p in "${PKGS[@]}"; do [[ " ${missing[*]} " == *" $p "* ]] || install+=("$p"); done
  sudo pacman -S --needed --noconfirm "${install[@]}"
fi

# --------------------------------------------------------------------------- libvirt
say "libvirt"
if ! systemctl is-active --quiet libvirtd.socket && ! systemctl is-active --quiet libvirtd; then
  sudo systemctl enable --now libvirtd.socket
fi
ok "libvirtd running"
if ! id -nG "$USER" | tr ' ' '\n' | grep -qx libvirt; then
  sudo usermod -aG libvirt "$USER"
  warn "added $USER to the 'libvirt' group: log out and in again (or run: newgrp libvirt)"
fi
if virsh -c qemu:///system net-info default &>/dev/null; then
  if ! virsh -c qemu:///system net-info default | grep -q 'Active:.*yes'; then
    virsh -c qemu:///system net-start default || sudo virsh net-start default
  fi
  virsh -c qemu:///system net-autostart default &>/dev/null || true
  ok "libvirt network 'default' active"
else
  warn "libvirt network 'default' not found (fine if your VM uses another network: set LIBVIRT_NET)"
fi

# --------------------------------------------------------------------------- sing-box
say "sing-box for the e2e lab"
need_official=$OFFICIAL_SINGBOX
if command -v sing-box &>/dev/null; then
  if sing-box version | grep -q with_clash_api; then
    ok "$(sing-box version | head -1) (with_clash_api)"
  else
    warn "the installed sing-box lacks with_clash_api; fetching the official build"
    need_official=1
  fi
else
  need_official=1
fi
if [[ $need_official -eq 1 ]]; then
  mkdir -p dev/bin
  arch=amd64; [[ "$(uname -m)" == aarch64 ]] && arch=arm64
  api=https://api.github.com/repos/SagerNet/sing-box/releases/latest
  url=$(curl -fsSL "$api" | python -c "import json,sys; a=[x for x in json.load(sys.stdin)['assets'] if x['name'].endswith('linux-$arch.tar.gz')]; print(a[0]['browser_download_url'])")
  tmp=$(mktemp -d)
  curl -fsSL "$url" -o "$tmp/sb.tgz"
  tar -xzf "$tmp/sb.tgz" -C "$tmp"
  install -m 755 "$(find "$tmp" -name sing-box -type f | head -1)" dev/bin/sing-box
  rm -rf "$tmp"
  ok "dev/bin/sing-box: $(dev/bin/sing-box version | head -1)"
  warn "the lab finds dev/bin/sing-box automatically; for your shell: export PATH=\"$ROOT/dev/bin:\$PATH\""
fi

# --------------------------------------------------------------------------- git
say "git"
if [[ ! -d .git ]]; then
  git init -q -b main
  ok "initialised an empty repository (make your first commit when ready)"
else
  ok "repository exists"
fi
git config core.autocrlf false        # .gitattributes decides line endings (CRLF for .bat/.ps1)

# --------------------------------------------------------------------------- VM config
say "VM settings"
if [[ ! -f dev/vm/vm.conf ]]; then
  cp dev/vm/vm.conf.example dev/vm/vm.conf
  doms=$(virsh -c qemu:///system list --all --name 2>/dev/null | sed '/^$/d' | tr '\n' ' ' || true)
  warn "created dev/vm/vm.conf - set VM_NAME (your VMs: ${doms:-none found}) and WIN_USER"
else
  ok "dev/vm/vm.conf exists"
fi

# --------------------------------------------------------------------------- Claude Code
say "Claude Code"
if command -v claude &>/dev/null; then
  ok "claude $(claude --version 2>/dev/null | head -1)"
else
  warn "Claude Code not found. Install it (see https://docs.claude.com/en/docs/claude-code/setup), then run 'claude' in $ROOT"
fi

say "quick self-check"
make -s test >/dev/null && ok "unit tests pass" || warn "unit tests failed: run 'make test'"

cat <<EOF

Next steps
  1. edit dev/vm/vm.conf (VM_NAME, WIN_USER)
  2. make vm-fetch          # installers for the VM (once)
  3. make vm-bootstrap      # ssh into the VM (once; follow the prompt)
  4. make vm-snapshot       # clean base for full runs (once, optional)
  5. make vm-all            # the whole Windows suite
  Run 'make help' for everything else.
EOF
