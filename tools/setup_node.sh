#!/usr/bin/env bash
#
# Prepares a Linux (Ubuntu/Debian) machine for the Kilotech cluster. Every step first checks
# whether it is already done properly and only fixes what is missing, so it is safe to re-run.
#
#   1. base packages: git, ssh, curl, python3
#   2. one GitHub deploy key per repo (~/.ssh/<repo>_deploy_ed25519), plus a Host alias for
#      it in ~/.ssh/config. The public keys are printed so you can add them on GitHub.
#   3. Docker Engine and the compose plugin, the service enabled, and you in the docker group
#   4. Ollama installed and running, and the model pulled (default: gemma4)
#   5. kilotech_hardware and kilotech_llm_local cloned into /srv through the deploy keys
#   6. a .venv in each /srv repo with all of its dependencies installed
#
# Run it as your normal user, not with sudo. It asks for your sudo password when it needs it.
#
#   tools/setup_node.sh                      # check everything, fix what is missing
#   tools/setup_node.sh --check              # only report, change nothing
#   tools/setup_node.sh --skip docker,model  # skip steps: prereqs keys docker ollama model repos venvs
#   tools/setup_node.sh --model qwen2.5:3b   # pull a different model
#   tools/setup_node.sh --non-interactive    # never wait for input (e.g. for deploy keys)
#
# Environment overrides: KILOTECH_SRV_DIR (/srv), KILOTECH_OLLAMA_MODEL (gemma4),
# KILOTECH_GITHUB_ORG (ka-moamoa).

set -uo pipefail

SRV_DIR=${KILOTECH_SRV_DIR:-/srv}
MODEL=${KILOTECH_OLLAMA_MODEL:-gemma4}
GITHUB_ORG=${KILOTECH_GITHUB_ORG:-ka-moamoa}
REPOS=(kilotech_hardware kilotech_llm_local)
STEPS=(prereqs keys docker ollama model repos venvs)
OLLAMA_URL=http://127.0.0.1:11434
SSH_CONFIG=$HOME/.ssh/config
USER=${USER:-$(id -un)}

CHECK_ONLY=0
INTERACTIVE=0
[[ -t 0 && -t 1 ]] && INTERACTIVE=1
SKIP=","
RELOGIN=0

usage() { sed -n '3,/^$/s/^# \{0,1\}//p' "$0"; }

while (($#)); do
  case $1 in
    --check) CHECK_ONLY=1 ;;
    --skip) SKIP+="${2:?--skip needs a comma-separated list}," ; shift ;;
    --skip=*) SKIP+="${1#*=}," ;;
    --model) MODEL=${2:?--model needs a name}; shift ;;
    --model=*) MODEL=${1#*=} ;;
    --srv-dir) SRV_DIR=${2:?--srv-dir needs a path}; shift ;;
    --srv-dir=*) SRV_DIR=${1#*=} ;;
    --non-interactive) INTERACTIVE=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
SRV_DIR=${SRV_DIR%/}

for s in ${SKIP//,/ }; do
  [[ " ${STEPS[*]} " == *" $s "* ]] || { echo "unknown step for --skip: $s (steps: ${STEPS[*]})" >&2; exit 2; }
done
skipped() { [[ $SKIP == *",$1,"* ]]; }

# ---------------------------------------------------------------- output and bookkeeping

if [[ -t 1 ]]; then
  B=$'\e[1m' RED=$'\e[31m' GRN=$'\e[32m' YLW=$'\e[33m' N=$'\e[0m'
else
  B="" RED="" GRN="" YLW="" N=""
fi
section() { printf '\n%s== %s%s\n' "$B" "$*" "$N"; }
info() { printf '   %s\n' "$*"; }
warn() { printf '   %s%s%s\n' "$YLW" "$*" "$N"; }
die() { printf '%serror:%s %s\n' "$RED" "$N" "$*" >&2; exit 1; }

RES_NAME=() RES_STATE=() RES_NOTE=()
record() { RES_NAME+=("$1"); RES_STATE+=("$2"); RES_NOTE+=("${3:-}"); }

# step <name> <check_fn> <fix_fn> [args...]
#   check_fn returns 0 when the thing is done properly, otherwise sets NOTE and returns 1.
#   fix_fn returns 0 when fixed (the check is then re-run), 2 when the user has to do
#   something first, anything else on failure. Either one sets NOTE to explain.
NOTE=""
step() {
  local name=$1 check=$2 fix=$3 why rc
  shift 3
  NOTE=""
  if "$check" "$@"; then
    info "${GRN}ok${N}       $name"; record "$name" ok; return 0
  fi
  why=$NOTE
  if ((CHECK_ONLY)); then
    info "${YLW}missing${N}  $name: $why"; record "$name" missing "$why"; return 1
  fi
  info "fixing   $name: $why"
  NOTE=""
  "$fix" "$@"; rc=$?
  if ((rc == 0)); then
    NOTE=""
    if "$check" "$@"; then info "${GRN}fixed${N}    $name"; record "$name" fixed; return 0; fi
  fi
  if ((rc == 2)); then
    warn "ACTION   $name: $NOTE"; record "$name" action "$NOTE"; return 2
  fi
  [[ -n $NOTE ]] || NOTE=$why
  printf '   %sFAILED%s   %s: %s\n' "$RED" "$N" "$name" "$NOTE"; record "$name" failed "$NOTE"
  return 1
}

# Starts a step group, or records it as skipped.
group() {
  if skipped "$1"; then record "$1" skipped "--skip $1"; return 1; fi
  section "$2"
}

wait_for() { # wait_for <fn> <seconds>
  local fn=$1 n=$2
  while ((n-- > 0)); do "$fn" && return 0; sleep 1; done
  return 1
}

has_systemd() { [[ -d /run/systemd/system ]]; }

# ---------------------------------------------------------------- sudo and apt

KEEPALIVE=""
SUDO_READY=0
trap '[[ -n $KEEPALIVE ]] && kill "$KEEPALIVE" 2>/dev/null' EXIT

# Asks for the sudo password once, then keeps the credentials fresh so long downloads
# (Docker, Ollama, the model) do not stop at a second password prompt.
ensure_sudo() {
  ((EUID == 0 || SUDO_READY)) && return 0
  ((CHECK_ONLY)) && return 0
  sudo -v || { NOTE="sudo failed"; return 1; }
  ( while kill -0 "$$" 2>/dev/null; do sudo -n true 2>/dev/null; sleep 60; done ) &
  KEEPALIVE=$!
  SUDO_READY=1
}

# In --check mode this never prompts: checks that need root just fail with a note.
as_root() {
  if ((EUID == 0)); then "$@"; return; fi
  if ((CHECK_ONLY)); then sudo -n "$@" 2>/dev/null; return; fi
  ensure_sudo || return 1
  sudo "$@"
}

APT_UPDATED=0
apt_install() {
  command -v apt-get >/dev/null || { NOTE="apt-get not found; install these yourself: $*"; return 1; }
  if ((!APT_UPDATED)); then
    as_root apt-get update -q || { NOTE="apt-get update failed"; return 1; }
    APT_UPDATED=1
  fi
  as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -q "$@" \
    || { NOTE="apt-get install $* failed"; return 1; }
}

# ---------------------------------------------------------------- 1. base packages

PREREQ_CMDS=(git ssh ssh-keygen curl python3)

check_prereqs() {
  local missing=() c
  for c in "${PREREQ_CMDS[@]}"; do command -v "$c" >/dev/null || missing+=("$c"); done
  ((${#missing[@]} == 0)) || { NOTE="missing: ${missing[*]}"; return 1; }
}
fix_prereqs() { apt_install git openssh-client curl ca-certificates python3; }

# ---------------------------------------------------------------- 2. deploy keys

key_path() { echo "$HOME/.ssh/${1}_deploy_ed25519"; }
host_alias() { echo "github.com-$1"; }
remote_url() { echo "git@$(host_alias "$1"):$GITHUB_ORG/$1.git"; }
block_begin() { echo "# >>> kilotech deploy key: $1 (managed by kilotech_hardware/tools/setup_node.sh)"; }
block_end() { echo "# <<< kilotech deploy key: $1"; }

ssh_block() {
  block_begin "$1"
  printf 'Host %s\n' "$(host_alias "$1")"
  printf '    HostName github.com\n'
  printf '    User git\n'
  printf '    IdentityFile ~/.ssh/%s_deploy_ed25519\n' "$1"
  printf '    IdentitiesOnly yes\n'
  printf '    StrictHostKeyChecking accept-new\n'
  block_end "$1"
}

current_block() {
  [[ -f $SSH_CONFIG ]] || return 0
  awk -v b="$(block_begin "$1")" -v e="$(block_end "$1")" \
    '$0 == b { f = 1 } f { print } f && $0 == e { exit }' "$SSH_CONFIG"
}

check_key() {
  local repo=$1 key alias eff
  key=$(key_path "$repo")
  alias=$(host_alias "$repo")
  [[ -f $key && -f $key.pub ]] || { NOTE="no deploy key at $key"; return 1; }
  [[ $(stat -c %a "$key") == 600 ]] || { NOTE="$key permissions are not 600"; return 1; }
  [[ "$(current_block "$repo")" == "$(ssh_block "$repo")" ]] \
    || { NOTE="no up-to-date 'Host $alias' entry in $SSH_CONFIG"; return 1; }
  # What ssh will actually use, in case another entry in the config shadows ours.
  eff=$(ssh -G "$alias" 2>/dev/null)
  grep -qixF "hostname github.com" <<<"$eff" \
    && grep -qixF -e "identityfile $key" -e "identityfile ~/.ssh/${repo}_deploy_ed25519" <<<"$eff" \
    || { NOTE="another entry in $SSH_CONFIG overrides 'Host $alias'"; return 1; }
}

fix_key() {
  local repo=$1 key tmp
  key=$(key_path "$repo")
  install -d -m 700 "$HOME/.ssh"
  if [[ ! -f $key ]]; then
    ssh-keygen -q -t ed25519 -N "" -C "$repo deploy key ($(uname -n))" -f "$key" \
      || { NOTE="ssh-keygen failed"; return 1; }
  elif [[ ! -f $key.pub ]]; then
    ssh-keygen -y -f "$key" >"$key.pub" || { NOTE="could not rebuild $key.pub"; return 1; }
  fi
  chmod 600 "$key"
  chmod 644 "$key.pub"

  # Replace our managed block (if any) with the current one; leave the rest untouched.
  [[ -f $SSH_CONFIG ]] || { touch "$SSH_CONFIG" && chmod 600 "$SSH_CONFIG"; }
  tmp=$(mktemp)
  awk -v b="$(block_begin "$repo")" -v e="$(block_end "$repo")" \
    '$0 == b { skip = 1 } !skip { print } skip && $0 == e { skip = 0 }' "$SSH_CONFIG" >"$tmp"
  { cat "$tmp"; [[ -s $tmp ]] && echo; ssh_block "$repo"; } >"$SSH_CONFIG"
  rm -f "$tmp"
}

print_key() {
  local repo=$1
  printf '\n   %s%s%s\n' "$B" "$repo" "$N"
  info "  Add at:  https://github.com/$GITHUB_ORG/$repo/settings/keys/new"
  info "  Title:   $(uname -n) $SRV_DIR/$repo"
  info "  Key:     $(cat "$(key_path "$repo").pub")"
}

# ---------------------------------------------------------------- 3. GitHub access + /srv clones

ACCESS_DENIED=0 ACCESS_WHY=""
check_access() {
  local err
  if [[ ! -f $(key_path "$1").pub || -z $(current_block "$1") ]]; then
    ACCESS_DENIED=0 ACCESS_WHY="no deploy key for $1 yet (see the keys step)"
    NOTE=$ACCESS_WHY
    return 1
  fi
  err=$(GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10" \
    timeout 30 git ls-remote "$(remote_url "$1")" HEAD 2>&1 >/dev/null) && return 0
  if grep -qiE "permission denied|repository not found" <<<"$err"; then
    ACCESS_DENIED=1 ACCESS_WHY="GitHub does not accept the deploy key for $GITHUB_ORG/$1 yet"
  else
    ACCESS_DENIED=0 ACCESS_WHY="cannot reach GitHub over ssh: $(head -n1 <<<"${err:-timed out}")"
  fi
  NOTE=$ACCESS_WHY
  return 1
}

fix_access() {
  local repo=$1 ans
  [[ -f $(key_path "$repo").pub ]] || { NOTE="no deploy key (the keys step was skipped or failed)"; return 1; }
  ((ACCESS_DENIED)) || { NOTE=$ACCESS_WHY; return 1; }
  print_key "$repo"
  while ((INTERACTIVE)); do
    echo
    read -r -p "   Press Enter once the key is added to check again, or type s to skip: " ans || break
    [[ $ans == [sS]* ]] && break
    check_access "$repo" && return 0
    warn "GitHub still rejects the key."
  done
  NOTE="add the deploy key above to $GITHUB_ORG/$repo on GitHub, then re-run"
  return 2
}

not_owned() { find "$1" ! -user "$USER" -print -quit 2>/dev/null; }

check_repo() {
  local repo=$1 dir=$SRV_DIR/$1
  [[ -d $dir ]] || { NOTE="$dir does not exist"; return 1; }
  [[ -z $(not_owned "$dir") ]] || { NOTE="$dir has files not owned by $USER"; return 1; }
  [[ -e $dir/.git ]] && git -C "$dir" rev-parse HEAD >/dev/null 2>&1 \
    || { NOTE="$dir is not a git clone"; return 1; }
  [[ $(git -C "$dir" remote get-url origin 2>/dev/null) == "$(remote_url "$repo")" ]] \
    || { NOTE="origin does not use the deploy key ($(remote_url "$repo"))"; return 1; }
}

fix_repo() {
  local repo=$1 dir=$SRV_DIR/$1 url cur
  url=$(remote_url "$repo")
  if [[ -d $dir && -n $(not_owned "$dir") ]]; then
    as_root chown -R "$USER:$(id -gn)" "$dir" || { NOTE="could not chown $dir"; return 1; }
  fi

  if [[ ! -d $dir || -z $(ls -A "$dir") ]]; then
    check_access "$repo" || { NOTE="cannot clone until the deploy key is added on GitHub"; return 2; }
    as_root mkdir -p "$dir" && as_root chown "$USER:$(id -gn)" "$dir" \
      || { NOTE="could not create $dir"; return 1; }
    git clone "$url" "$dir" || { NOTE="git clone $url failed"; return 1; }
    return 0
  fi

  [[ -e $dir/.git ]] || { NOTE="$dir is not empty and not a git clone; move it aside and re-run"; return 1; }
  cur=$(git -C "$dir" remote get-url origin 2>/dev/null || true)
  if [[ -z $cur ]]; then
    git -C "$dir" remote add origin "$url"
  elif [[ $cur != "$url" ]]; then
    if [[ $cur =~ [/:]$GITHUB_ORG/$repo(\.git)?/?$ ]]; then
      info "switching origin from $cur to $url"
      git -C "$dir" remote set-url origin "$url"
    else
      NOTE="origin is $cur, which is not $GITHUB_ORG/$repo; not changing it"
      return 1
    fi
  fi
}

# ---------------------------------------------------------------- 4. Docker

in_docker_group() { id -nG "$USER" | tr ' ' '\n' | grep -qx docker; }

check_docker() {
  command -v docker >/dev/null || { NOTE="Docker is not installed"; return 1; }
  docker compose version >/dev/null 2>&1 || { NOTE="the docker compose plugin is missing"; return 1; }
  if has_systemd; then
    { systemctl is-enabled --quiet docker && systemctl is-active --quiet docker; } 2>/dev/null \
      || { NOTE="the docker service is not enabled and running"; return 1; }
  fi
  docker info >/dev/null 2>&1 || as_root docker info >/dev/null 2>&1 \
    || { NOTE="the Docker daemon is not responding"; return 1; }
  ((EUID == 0)) || in_docker_group || { NOTE="$USER is not in the docker group"; return 1; }
}

# Docker's official apt repository: https://docs.docker.com/engine/install/ubuntu/
install_docker_ce() {
  local distro codename tmp
  command -v apt-get >/dev/null \
    || { NOTE="automatic install only supports Ubuntu/Debian; see https://docs.docker.com/engine/install/"; return 1; }
  case "${ID:-}:${ID_LIKE:-}" in
    ubuntu:* | *:*ubuntu*) distro=ubuntu; codename=${UBUNTU_CODENAME:-${VERSION_CODENAME:-}} ;;
    debian:* | *:*debian*) distro=debian; codename=${VERSION_CODENAME:-} ;;
    *) NOTE="automatic install only supports Ubuntu/Debian; see https://docs.docker.com/engine/install/"; return 1 ;;
  esac
  [[ -n $codename ]] || { NOTE="could not read the release codename from /etc/os-release"; return 1; }

  apt_install ca-certificates curl || return 1
  as_root install -m 0755 -d /etc/apt/keyrings
  as_root curl -fsSL "https://download.docker.com/linux/$distro/gpg" -o /etc/apt/keyrings/docker.asc \
    || { NOTE="could not download Docker's apt key"; return 1; }
  as_root chmod a+r /etc/apt/keyrings/docker.asc
  tmp=$(mktemp)
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$distro $codename stable" >"$tmp"
  as_root install -m 0644 "$tmp" /etc/apt/sources.list.d/docker.list
  rm -f "$tmp"
  APT_UPDATED=0
  apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

fix_docker() {
  if ! command -v docker >/dev/null; then
    install_docker_ce || return 1
  elif ! docker compose version >/dev/null 2>&1; then
    apt_install docker-compose-plugin || apt_install docker-compose-v2 \
      || { NOTE="could not install the docker compose plugin"; return 1; }
  fi

  if has_systemd; then
    as_root systemctl enable --now docker || { NOTE="could not enable and start the docker service"; return 1; }
  elif ! as_root docker info >/dev/null 2>&1; then
    as_root service docker start || { NOTE="no systemd, and 'service docker start' failed"; return 1; }
  fi

  if ((EUID != 0)) && ! in_docker_group; then
    getent group docker >/dev/null || as_root groupadd docker
    as_root usermod -aG docker "$USER" || { NOTE="could not add $USER to the docker group"; return 1; }
    RELOGIN=1
  fi
}

# ---------------------------------------------------------------- 5. Ollama + model

ollama_up() { curl -fsS --max-time 3 "$OLLAMA_URL/api/version" >/dev/null 2>&1; }
ollama_unit() { has_systemd && systemctl cat ollama.service >/dev/null 2>&1; }

check_ollama() {
  command -v ollama >/dev/null || { NOTE="Ollama is not installed"; return 1; }
  if ollama_unit; then
    { systemctl is-enabled --quiet ollama && systemctl is-active --quiet ollama; } 2>/dev/null \
      || { NOTE="the ollama service is not enabled and running"; return 1; }
  fi
  ollama_up || { NOTE="the Ollama server is not answering on $OLLAMA_URL"; return 1; }
}

fix_ollama() {
  local tmp rc
  if ! command -v ollama >/dev/null; then
    ensure_sudo || return 1   # the official installer uses sudo itself
    command -v zstd >/dev/null || apt_install zstd || true
    tmp=$(mktemp)
    curl -fsSL https://ollama.com/install.sh -o "$tmp" || { rm -f "$tmp"; NOTE="could not download the Ollama installer"; return 1; }
    sh "$tmp"; rc=$?
    rm -f "$tmp"
    ((rc == 0)) || { NOTE="the Ollama installer failed"; return 1; }
  fi

  if ollama_unit; then
    as_root systemctl enable --now ollama || { NOTE="could not enable and start the ollama service"; return 1; }
  elif ! ollama_up; then
    mkdir -p "$HOME/.ollama"
    info "no systemd service; starting 'ollama serve' in the background (log: ~/.ollama/serve.log)"
    nohup ollama serve >>"$HOME/.ollama/serve.log" 2>&1 &
    disown
  fi
  wait_for ollama_up 30 || { NOTE="Ollama did not start answering on $OLLAMA_URL"; return 1; }
}

check_model() {
  command -v ollama >/dev/null && ollama_up || { NOTE="Ollama is not running, so the model cannot be checked"; return 1; }
  ollama show "$MODEL" >/dev/null 2>&1 || { NOTE="$MODEL is not pulled"; return 1; }
}

fix_model() {
  command -v ollama >/dev/null && ollama_up || { NOTE="Ollama is not running (see the ollama step)"; return 1; }
  ollama pull "$MODEL" || { NOTE="ollama pull $MODEL failed (wrong name? use --model or KILOTECH_OLLAMA_MODEL)"; return 1; }
}

# ---------------------------------------------------------------- 6. virtual environments

# Files whose contents decide the installed dependencies; a change triggers a reinstall.
dep_files() {
  case $1 in
    kilotech_hardware) echo requirements-dev.txt common/pyproject.toml gateway/pyproject.toml worker/pyproject.toml storage/pyproject.toml ;;
    kilotech_llm_local) echo pyproject.toml ;;
  esac
}
# Modules that must be importable from the venv.
dep_modules() {
  case $1 in
    kilotech_hardware) echo kilotech_common kilotech_gateway kilotech_worker kilotech_storage pytest ;;
    kilotech_llm_local) echo kilotech_llm_local numpy sentence_transformers ;;
  esac
}
deps_hash() {
  local f
  (cd "$SRV_DIR/$1" && for f in $(dep_files "$1"); do cat "$f"; done) 2>&1 | sha256sum | cut -d' ' -f1
}
py_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; }
FIND_SPEC='import importlib.util as u, sys
missing = [m for m in sys.argv[1:] if u.find_spec(m) is None]
print(" ".join(missing)); sys.exit(1 if missing else 0)'

check_venv() {
  local repo=$1 dir=$SRV_DIR/$1 venv=$SRV_DIR/$1/.venv missing
  [[ -d $dir/.git ]] || { NOTE="$dir is not cloned yet"; return 1; }
  [[ -x $venv/bin/python ]] && py_ok "$venv/bin/python" || { NOTE="no working Python 3.10+ venv at $venv"; return 1; }
  [[ $(cat "$venv/.kilotech-deps" 2>/dev/null) == "$(deps_hash "$repo")" ]] \
    || { NOTE="dependencies are not installed or out of date"; return 1; }
  # shellcheck disable=SC2046  # module names are plain words
  missing=$("$venv/bin/python" -c "$FIND_SPEC" $(dep_modules "$repo")) || { NOTE="missing modules: $missing"; return 1; }
}

fix_venv() {
  local repo=$1 dir=$SRV_DIR/$1 venv=$SRV_DIR/$1/.venv args=()
  [[ -d $dir/.git ]] || { NOTE="clone $dir first (see the repos step)"; return 2; }
  py_ok python3 || { NOTE="python3 is $(python3 -V 2>&1); 3.10+ is required"; return 1; }
  python3 -c 'import ensurepip, venv' 2>/dev/null || apt_install python3-venv || return 1

  if [[ -e $venv ]] && ! { [[ -x $venv/bin/python ]] && py_ok "$venv/bin/python"; }; then
    info "removing broken venv $venv"
    rm -rf "$venv"
  fi
  [[ -x $venv/bin/python ]] || python3 -m venv "$venv" || { NOTE="python3 -m venv $venv failed"; return 1; }

  case $repo in
    kilotech_hardware) args=(-r requirements-dev.txt) ;;
    kilotech_llm_local) args=(-e ".[cli]") ;;
  esac
  rm -f "$venv/.kilotech-deps"
  (cd "$dir" && "$venv/bin/python" -m pip install -q --upgrade pip && "$venv/bin/python" -m pip install "${args[@]}") \
    || { NOTE="pip install ${args[*]} failed"; return 1; }
  deps_hash "$repo" >"$venv/.kilotech-deps"
}

# ---------------------------------------------------------------- summary

summary() {
  local i state color ok=1 repo shown=0
  section "Summary"
  for i in "${!RES_NAME[@]}"; do
    state=${RES_STATE[$i]}
    case $state in
      ok | fixed) color=$GRN ;;
      skipped) color="" ;;
      missing | action) color=$YLW; ok=0 ;;
      *) color=$RED; ok=0 ;;
    esac
    printf '   %s%-8s%s %s%s\n' "$color" "$state" "$N" "${RES_NAME[$i]}" "${RES_NOTE[$i]:+  ($YLW${RES_NOTE[$i]}$N)}"
  done

  for repo in "${REPOS[@]}"; do
    [[ -f $(key_path "$repo").pub ]] || continue
    ((shown++)) || section "Deploy keys (add each one to its repo on GitHub: Settings > Deploy keys)"
    print_key "$repo"
  done
  ((shown)) && info "" && info "Leave \"Allow write access\" off unless you push from this machine."

  if ((RELOGIN)); then
    echo
    warn "You were added to the docker group. Log out and back in (or run 'newgrp docker')"
    warn "before using docker without sudo."
  fi
  echo
  if ((ok)); then
    info "${GRN}All done.${N} Deploy from $SRV_DIR/kilotech_hardware by following the README in this"
    info "machine's role folder (gateway/, storage/ or worker/)."
  else
    info "Some steps are not done yet (see above). Fix them and re-run: everything already done is skipped."
  fi
  return $((1 - ok))
}

# ---------------------------------------------------------------- main

main() {
  local repo pending=()
  [[ $(uname -s) == Linux ]] || die "this script is for Linux machines"
  if ((EUID == 0)) && [[ -n ${SUDO_USER:-} ]]; then
    die "run this as your normal user, without sudo (it asks for sudo when it needs it), so the deploy keys and /srv clones belong to you"
  fi
  # shellcheck disable=SC1091
  [[ -r /etc/os-release ]] && . /etc/os-release

  section "Kilotech node setup ($( ((CHECK_ONLY)) && echo "check only" || echo "check and fix"))"
  info "user: $USER   repos: $SRV_DIR/{$(IFS=,; echo "${REPOS[*]}")}   model: $MODEL"

  if group prereqs "Base packages"; then
    step "base packages" check_prereqs fix_prereqs
  fi

  if group keys "Deploy keys and ~/.ssh/config"; then
    for repo in "${REPOS[@]}"; do
      step "deploy key: $repo" check_key fix_key "$repo"
    done
    # Show keys GitHub does not know yet right away, so they can be added while the
    # installs below run. Access is checked again before cloning.
    for repo in "${REPOS[@]}"; do
      [[ -f $(key_path "$repo").pub ]] && ! check_access "$repo" && ((ACCESS_DENIED)) && pending+=("$repo")
    done
    if ((${#pending[@]})); then
      echo
      warn "GitHub does not accept these deploy keys yet. Add each one to its repo now"
      warn "(Settings > Deploy keys > Add deploy key); access is checked again before cloning."
      for repo in "${pending[@]}"; do print_key "$repo"; done
    fi
  fi

  if group docker "Docker"; then
    step "docker" check_docker fix_docker
  fi
  if group ollama "Ollama"; then
    step "ollama" check_ollama fix_ollama
  fi
  if group model "Ollama model"; then
    step "model $MODEL" check_model fix_model
  fi

  if group repos "Repos in $SRV_DIR"; then
    for repo in "${REPOS[@]}"; do
      step "GitHub access: $repo" check_access fix_access "$repo"
      step "$SRV_DIR/$repo" check_repo fix_repo "$repo"
    done
  fi

  if group venvs "Virtual environments"; then
    for repo in "${REPOS[@]}"; do
      step "venv: $SRV_DIR/$repo/.venv" check_venv fix_venv "$repo"
    done
  fi

  summary
}

main
