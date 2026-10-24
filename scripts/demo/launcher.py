"""One command to run the RoleCraft demo, and one to tell whether it is fit to record.

    scripts/demo/up.sh       [--provider deepseek] [--env-file models.env] [--api-port 18562] ...
    scripts/demo/check.sh    [--json] [--no-encoder-load]
    scripts/demo/status.sh
    scripts/demo/down.sh

(``.ps1`` versions on Windows.) Everything lives in one run directory, by default
``runs/demo-stack`` (ignored by Git): the scenario catalog, the deployment credential key,
the SQLite database, logs, process ids and the demo pack's continue codes. Running ``up``
again reuses the database and its codes; ``--reimport`` replaces the demo sessions and
issues new codes.

Standard library only: it runs before the project environment exists and creates it with
``uv sync``. Model keys are never read or written here. The services read them from the
``CAREER_LAB_*_KEY_FILE`` files named in the environment or in ``--env-file``; values of
variables that may hold secrets are never printed or saved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import locale
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "apps/web"
WINDOWS = os.name == "nt"
DEMO_PACK = REPO / "demo/demo-pack-v1.json.gz"
CATALOGS = {
    "demo": REPO / "demo/catalog.json",  # published packages plus the IT service-desk domain
    "published": REPO / "tests/regression/published-catalog.json",
}
KEY_ID = "demo-stack-v1"
# Set by the launcher for every process; a caller's own value would split the deployment.
CONTROLLED = {
    "CAREER_LAB_SCENARIO_CATALOG",
    "CAREER_LAB_SCENARIO_ARCHIVE",
    "CAREER_LAB_CREDENTIAL_KEY_ID",
    "CAREER_LAB_CREDENTIAL_KEY",
    "CAREER_LAB_DATABASE_URL",
}
ENV_PREFIXES = ("CAREER_LAB_", "HF_", "TRANSFORMERS_")
SLOTS = ("ROLES", "JUDGE", "SUPPORT", "ASSISTANT")
RECOGNIZERS = (
    "retrieval-e5",
    "scope-mahalanobis-v1",
    "intent-tfidf-lr-v1",
    "behavior-v1",
    "relation-stack-v1",
)
CODE_LINE = re.compile(
    r"^(?P<code>[0-9A-Z]{4}(?:-[0-9A-Z]{4}){4})\s{2}(?P<label>.+?)\s{2}"
    r"\((?P<scenario>[^,]+), (?P<language>zh|en), (?P<status>[^)]+)\)$"
)
ENGINE_PARAM = re.compile(r"workbench-engine\.js\?v=([A-Za-z0-9._-]+)")
LANG = "en"


def t(zh: str, en: str) -> str:
    return zh if LANG == "zh" else en


# ---------------------------------------------------------------- pure helpers (unit-tested)


def is_secret_name(name: str) -> bool:
    """Variables whose value may be a secret: reported as set, never by value."""
    upper = name.upper()
    if upper.endswith("_KEY_FILE") or upper.endswith("_KEY_ID"):
        return False
    return any(word in upper for word in ("KEY", "SECRET", "TOKEN", "PASSWORD", "DATABASE_URL"))


def parse_env_file(text: str) -> tuple[dict[str, str], list[str]]:
    """``KEY=VALUE`` lines (``export`` and quotes allowed); returns values and ignored names."""
    values: dict[str, str] = {}
    ignored: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            ignored.append(name or raw.strip())
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if not name.startswith(ENV_PREFIXES) or name in CONTROLLED:
            ignored.append(name)
            continue
        values[name] = value
    return values, ignored


def public_env(env: dict[str, str]) -> dict[str, str]:
    """The model and recognizer configuration as it may be saved and shown."""
    shown = {}
    for name in sorted(env):
        if not name.startswith(ENV_PREFIXES) or name in CONTROLLED:
            continue
        shown[name] = "(set)" if is_secret_name(name) else env[name]
    return shown


def parse_import_output(text: str) -> tuple[list[dict], list[str]]:
    """Continue codes and warnings printed by ``scripts.recognition.demo_pack import``."""
    codes, warnings = [], []
    for line in text.splitlines():
        match = CODE_LINE.match(line.strip())
        if match:
            codes.append(match.groupdict())
        elif line.startswith(("!", "- ")):
            warnings.append(line.strip())
    return codes, warnings


def parse_worker_log(text: str) -> dict:
    """Model slots and recognizer states from the worker's startup lines (last start wins)."""
    slots: dict[str, dict] = {}
    recognizers: dict[str, dict] = {}
    for line in text.splitlines():
        slot = re.match(
            r"career-lab model slot (\w+): provider=(\S+) model=(\S+) fingerprint=(\S+)", line
        )
        if slot:
            if slot.group(1) == "ROLES":
                slots, recognizers = {}, {}
            slots[slot.group(1)] = {"provider": slot.group(2), "model": slot.group(3)}
            continue
        loaded = re.match(r"career-lab recognizer (\S+): loaded revision=(\S+)", line)
        if loaded:
            recognizers[loaded.group(1)] = {"loaded": True, "revision": loaded.group(2)}
            continue
        fallback = re.match(r"career-lab recognizer (\S+): rule-fallback \((\w+)\)", line)
        if fallback:
            recognizers[fallback.group(1)] = {"loaded": False, "reason": fallback.group(2)}
    return {"slots": slots, "recognizers": recognizers}


def verdict(findings: list[dict]) -> str:
    """``blocked`` if anything stops recording, ``replay`` if the live system is not full."""
    levels = {f["level"] for f in findings}
    if "block" in levels:
        return "blocked"
    if "replay" in levels:
        return "replay"
    return "full"


def tree_fingerprint(root: Path, members: list[str]) -> str:
    """SHA-256 over relative paths and file hashes, so a ZIP copy without Git works too."""
    lines = []
    for member in members:
        base = root / member
        files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
        for file in files:
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            lines.append(f"{file.relative_to(root).as_posix()}\t{digest}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


# ---------------------------------------------------------------- environment and processes

WEB_SOURCES = [
    "index.html",
    "package.json",
    "package-lock.json",
    "vite.config.ts",
    "tsconfig.json",
    "src",
    "public",
]


def web_sources() -> list[str]:
    return [m for m in WEB_SOURCES if (WEB / m).exists()]


def venv_dir() -> Path:
    value = os.environ.get("UV_PROJECT_ENVIRONMENT")
    path = Path(value) if value else REPO / ".venv"
    return path if path.is_absolute() else REPO / path


def venv_bin(name: str) -> Path:
    folder = venv_dir() / ("Scripts" if WINDOWS else "bin")
    return folder / (name + (".exe" if WINDOWS else ""))


def base_env(inherit_configuration: bool = True) -> dict[str, str]:
    """The caller's environment without stray Python paths; optionally without CAREER_LAB_*."""
    env = dict(os.environ)
    for name in ("PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME"):
        env.pop(name, None)
    for name in list(env):
        if name in CONTROLLED or (not inherit_configuration and name.startswith(ENV_PREFIXES)):
            env.pop(name)
    env.setdefault("NO_PROXY", "127.0.0.1,localhost")
    env.setdefault("no_proxy", env["NO_PROXY"])
    env["PYTHONUTF8"] = "1"
    return env


def deployment_env(run_dir: Path, configuration: dict[str, str]) -> dict[str, str]:
    """What every service of this run directory starts with: only the given configuration."""
    env = base_env(inherit_configuration=False)
    env.update(configuration)
    env["CAREER_LAB_SCENARIO_CATALOG"] = str(run_dir / "catalog.json")
    env["CAREER_LAB_SCENARIO_ARCHIVE"] = str(run_dir / "archive")
    env["CAREER_LAB_CREDENTIAL_KEY_ID"] = KEY_ID
    key_file = run_dir / "credential.key"
    if key_file.is_file():
        env["CAREER_LAB_CREDENTIAL_KEY"] = key_file.read_text(encoding="utf-8").strip()
    return env


def http_get(url: str, timeout: float = 3.0) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""
    except (urllib.error.URLError, OSError):
        return 0, b""


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) != 0


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if WINDOWS:
        listed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        )
        return str(pid) in listed.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pid_matches(pid: int, token: str) -> bool:
    """The pid still runs our command (pids are reused); Windows checks liveness only."""
    if WINDOWS:
        return pid_alive(pid)
    shown = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True)
    return token in shown.stdout


def spawn(cmd: list[str], cwd: Path, env: dict[str, str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists():
        log.replace(log.with_suffix(log.suffix + ".1"))
    handle = open(log, "ab")  # noqa: SIM115 - inherited by the detached child
    options: dict = {"cwd": cwd, "env": env, "stdin": subprocess.DEVNULL}
    options.update(stdout=handle, stderr=subprocess.STDOUT)
    if WINDOWS:
        options["creationflags"] = 0x00000200 | 0x00000008  # new process group, detached
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(cmd, **options)
    handle.close()
    return process.pid


def stop(pid: int, token: str) -> str:
    if not pid_alive(pid):
        return "gone"
    if not pid_matches(pid, token):
        return "not_ours"
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return "stopped"
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "gone"
    deadline = time.time() + 10
    while time.time() < deadline and pid_alive(pid):
        time.sleep(0.2)
    if pid_alive(pid):
        os.killpg(pid, signal.SIGKILL)
    return "stopped"


def tail(path: Path, lines: int = 15) -> str:
    if not path.is_file():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def fail(message: str, log: Path | None = None) -> None:
    print("\n✗ " + message, file=sys.stderr)
    if log is not None and tail(log):
        print(t(f"  {log} 最后几行：", f"  last lines of {log}:"), file=sys.stderr)
        print("    " + tail(log).replace("\n", "\n    "), file=sys.stderr)
    sys.exit(2)


def step(number: int, total: int, text: str) -> None:
    print(f"[{number}/{total}] {text}", flush=True)


def run(cmd: list[str], env: dict[str, str], cwd: Path = REPO, quiet: bool = True) -> str:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE if quiet else None,
        stderr=subprocess.STDOUT if quiet else None,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        output = (result.stdout or "").strip().splitlines()[-20:]
        fail(t("命令失败：", "command failed: ") + " ".join(cmd) + "\n    " + "\n    ".join(output))
    return result.stdout or ""


def read_state(run_dir: Path) -> dict | None:
    path = run_dir / "state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if not WINDOWS:
        path.chmod(0o600)


def wait_until(check, seconds: float, pid: int, log: Path, what: str) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if check():
            return
        if not pid_alive(pid):
            fail(t(f"{what}启动后退出了。", f"{what} exited during startup."), log)
        time.sleep(0.5)
    fail(t(f"{what}在 {seconds:.0f} 秒内没有就绪。", f"{what} not ready in {seconds:.0f} s."), log)


def git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
    except OSError:
        return "no-git"
    if result.returncode != 0:
        return "no-git"
    return result.stdout.strip() + ("+changes" if dirty.stdout.strip() else "")


def node_version() -> tuple[int, ...] | None:
    node = shutil.which("node")
    if not node:
        return None
    shown = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    numbers = re.findall(r"\d+", shown)
    return tuple(int(n) for n in numbers[:3]) if numbers else None


def engine_param(html: str) -> str | None:
    found = ENGINE_PARAM.search(html)
    return found.group(1) if found else None


# ---------------------------------------------------------------- up


def cmd_up(args) -> int:
    run_dir = args.run_dir
    state = read_state(run_dir)
    if state and any(pid_alive(p) for p in state.get("pids", {}).values()):
        print(t("这套环境已经在运行：", "This environment is already running:"))
        print_status(state)
        print(t("要重启先运行 down。", "Run down first to restart."))
        return 1
    extra: dict[str, str] = {
        k: v for k, v in os.environ.items() if k.startswith(ENV_PREFIXES) and k not in CONTROLLED
    }
    env_file = None
    if args.env_file:
        env_file = args.env_file.resolve()
        values, ignored = parse_env_file(env_file.read_text(encoding="utf-8"))
        extra.update(values)
        if ignored:
            print(t("env 文件里忽略了：", "Ignored in the env file: ") + ", ".join(ignored))
    encoder = args.encoder or bool(extra.get("CAREER_LAB_RELATION_ENCODER"))
    total = 8

    step(1, total, t("检查 uv、Node 与端口", "Checking uv, Node and ports"))
    if not shutil.which("uv"):
        fail(t("找不到 uv：", "uv not found: ") + "https://docs.astral.sh/uv/")
    version = node_version()
    if version is None or version < (22, 12):
        fail(t("需要 Node.js 22.12 以上。", "Node.js 22.12 or newer is required."))
    if not shutil.which("npm"):
        fail(t("找不到 npm。", "npm not found."))
    ports = {"api": args.api_port, "web": args.web_port}
    for name, port in ports.items():
        if not port_free(args.host, port):
            fail(
                t(
                    f"端口 {port}（{name}）已被占用；换 --{name}-port。",
                    f"Port {port} ({name}) is in use; pass --{name}-port.",
                )
            )

    step(2, total, t("同步 Python 环境（uv sync）", "Syncing the Python environment (uv sync)"))
    sync = ["uv", "sync", "--locked", "--inexact"] + (["--extra", "encoder"] if encoder else [])
    run(sync, base_env(), quiet=False)

    step(3, total, t("准备前端依赖与构建", "Preparing frontend dependencies and build"))
    run_dir.mkdir(parents=True, exist_ok=True)
    npm = shutil.which("npm")
    lock_hash = hashlib.sha256((WEB / "package-lock.json").read_bytes()).hexdigest()
    lock_stamp = run_dir / "npm-lock.sha256"
    stamped = lock_stamp.read_text().strip() if lock_stamp.is_file() else ""
    if not (WEB / "node_modules").is_dir() or stamped != lock_hash:
        run([npm, "ci", "--no-audit", "--no-fund"], base_env(), cwd=WEB)
        lock_stamp.write_text(lock_hash + "\n")
    build_stamp = run_dir / "web-build.json"
    built = json.loads(build_stamp.read_text()) if build_stamp.is_file() else {}
    source = tree_fingerprint(WEB, web_sources())
    dist_ok = (WEB / "dist/index.html").is_file()
    if not dist_ok or built.get("source") != source or built.get("dist") != dist_fingerprint():
        run([npm, "run", "build"], base_env(), cwd=WEB)
        engine = WEB / "public/workbench-engine.js"
        build_stamp.write_text(
            json.dumps(
                {
                    "source": source,
                    "dist": dist_fingerprint(),
                    "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
                    "engine_param": engine_param((WEB / "index.html").read_text("utf-8")),
                    "previous_engine": built.get("engine_sha256"),
                    "previous_param": built.get("engine_param"),
                    "head": git_head(),
                    "built_at": datetime.now().isoformat(timespec="seconds"),
                },
                indent=2,
            )
            + "\n"
        )
    else:
        print(t("  前端已是当前源码的构建，跳过。", "  Frontend build is current; skipped."))

    step(4, total, t("场景目录与本机凭据密钥", "Scenario catalog and local credential key"))
    catalog_env = base_env()
    catalog_env["ROLECRAFT_REGRESSION_CATALOG"] = str(CATALOGS[args.catalog])
    run(
        [
            str(venv_bin("python")),
            "-c",
            "import sys; from pathlib import Path; "
            "from scripts.regression.published import write_catalog; "
            "write_catalog(Path(sys.argv[1]))",
            str(run_dir / "catalog.json"),
        ],
        catalog_env,
    )
    key_file = run_dir / "credential.key"
    if not key_file.is_file():
        write_private(key_file, secrets.token_urlsafe(48) + "\n")
    env = deployment_env(run_dir, extra)
    database = run_dir / "rolecraft.db"

    step(5, total, t("演示包", "Demo pack"))
    codes_file = run_dir / "continue-codes.json"
    fresh = not database.exists()
    if args.no_demo_pack:
        print(t("  按 --no-demo-pack 跳过。", "  Skipped (--no-demo-pack)."))
    elif fresh or args.reimport:
        command = [str(venv_bin("python")), "-m", "scripts.recognition.demo_pack", "import"]
        command += ["--db", str(database), "--pack", str(DEMO_PACK)]
        command += ["--catalog", str(run_dir / "catalog.json")]
        output = run(command + (["--replace"] if args.reimport else []), env)
        codes, warnings = parse_import_output(output)
        for warning in warnings:
            print("  " + warning)
        write_private(codes_file, json.dumps(codes, ensure_ascii=False, indent=2) + "\n")
        print(t(f"  导入 {len(codes)} 局，继续码已存。", f"  Imported {len(codes)} sessions."))
    else:
        print(t("  数据库已存在，沿用原来的继续码。", "  Database exists; codes unchanged."))

    logs = run_dir / "logs"
    provider = ["--provider", args.provider]
    career_lab = str(venv_bin("career-lab"))
    api_url = f"http://{args.host}:{args.api_port}"
    web_url = f"http://{args.host}:{args.web_port}"
    pids: dict[str, int] = {}
    state = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "head": git_head(),
        "host": args.host,
        "ports": ports,
        "urls": {"api": api_url, "web": web_url},
        "pids": pids,
        "provider": args.provider,
        "catalog": args.catalog,
        "env_file": str(env_file) if env_file else None,
        "env": public_env(extra),
        "encoder_environment": encoder,
    }
    try:
        start_services(args, total, env, pids, state, logs, career_lab, provider)
    except SystemExit:
        for name, pid in pids.items():
            stop(pid, TOKENS.get(name, "career-lab"))
        state["pids"] = {}
        save_state(run_dir, state)
        raise
    print()
    print(t(f"打开 {web_url}/", f"Open {web_url}/"))
    print_codes(run_dir)
    print()
    cmd_check(args)
    return 0  # started; whether it is fit to record is check's exit code


def save_state(run_dir: Path, state: dict) -> None:
    (run_dir / "state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def start_services(args, total, env, pids, state, logs, career_lab, provider) -> None:
    """API, then workers, then the frontend; each is saved as soon as it runs."""
    run_dir = args.run_dir
    api_url, web_url = state["urls"]["api"], state["urls"]["web"]
    database_url = "sqlite:///" + (run_dir / "rolecraft.db").as_posix()
    step(6, total, t("启动 API", "Starting the API"))
    pids["api"] = spawn(
        [career_lab, "serve", "--host", args.host, "--port", str(args.api_port)]
        + ["--database-url", database_url]
        + provider,
        REPO,
        env,
        logs / "api.log",
    )
    save_state(run_dir, state)
    wait_until(
        lambda: http_get(api_url + "/health")[0] == 200, 120, pids["api"], logs / "api.log", "API"
    )

    step(7, total, t("启动 worker", "Starting the worker"))
    for index in range(1, args.workers + 1):
        name = f"worker-{index}"
        pids[name] = spawn(
            [career_lab, "worker", "--database-url", database_url] + provider,
            REPO,
            env,
            logs / f"{name}.log",
        )
        save_state(run_dir, state)
    first = logs / "worker-1.log"
    wait_until(
        lambda: len(parse_worker_log(tail(first, 200))["recognizers"]) >= len(RECOGNIZERS),
        300,
        pids["worker-1"],
        first,
        "worker",
    )

    step(8, total, t("启动前端", "Starting the frontend"))
    web_env = base_env(inherit_configuration=False)
    web_env["ROLECRAFT_API_TARGET"] = api_url
    vite = str(WEB / "node_modules/vite/bin/vite.js")
    pids["web"] = spawn(
        [shutil.which("node"), vite, "preview", "--host", args.host]
        + ["--port", str(args.web_port), "--strictPort"],
        WEB,
        web_env,
        logs / "web.log",
    )
    save_state(run_dir, state)
    wait_until(
        lambda: http_get(web_url + "/")[0] == 200 and http_get(web_url + "/api/health")[0] == 200,
        60,
        pids["web"],
        logs / "web.log",
        t("前端", "frontend"),
    )


def dist_fingerprint() -> str | None:
    dist = WEB / "dist"
    if not (dist / "index.html").is_file():
        return None
    return tree_fingerprint(dist, sorted(p.name for p in dist.iterdir()))


def print_codes(run_dir: Path) -> None:
    path = run_dir / "continue-codes.json"
    if not path.is_file():
        return
    codes = json.loads(path.read_text(encoding="utf-8"))
    if not codes:
        return
    print(
        t(
            "演示包继续码（首页「有继续码？」输入；只在这套部署有效）：",
            "Demo continue codes (home page → Have a continue code?; valid on this deployment):",
        )
    )
    for entry in codes:
        print(f"  {entry['code']}  {entry['label']}")


# ---------------------------------------------------------------- down and status


TOKENS = {"api": "career-lab", "web": "vite"}


def cmd_down(args) -> int:
    state = read_state(args.run_dir)
    if not state or not state.get("pids"):
        print(t("这套环境没有在运行的进程。", "Nothing from this environment is running."))
        return 0
    for name, pid in state.get("pids", {}).items():
        result = stop(pid, TOKENS.get(name, "career-lab"))
        label = {
            "stopped": t("已停止", "stopped"),
            "gone": t("已不在运行", "not running"),
            "not_ours": t("pid 已被别的进程占用，未动", "pid now belongs to another process"),
        }[result]
        print(f"  {name} ({pid}): {label}")
    state["pids"] = {}
    (args.run_dir / "state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return 0


def print_status(state: dict) -> None:
    for name, pid in state.get("pids", {}).items():
        alive = pid_alive(pid)
        print(f"  {name} ({pid}): " + (t("运行中", "running") if alive else t("已停", "stopped")))
    urls = state.get("urls", {})
    if urls:
        print(f"  web {urls.get('web')}/  ·  api {urls.get('api')}")


def cmd_status(args) -> int:
    state = read_state(args.run_dir)
    if not state:
        print(t("没有找到这套环境的运行记录。", "No running environment recorded here."))
        return 1
    print_status(state)
    print_codes(args.run_dir)
    return 0


# ---------------------------------------------------------------- check

SLOT_USE = {
    "ROLES": ("同事回复", "colleague replies"),
    "JUDGE": ("评审的语义评分项", "semantic review items"),
    "SUPPORT": ("依据核验", "support verification"),
    "ASSISTANT": ("知识助手回答", "knowledge-assistant answers"),
}
RECOGNIZER_NAMES = {
    "retrieval-e5": ("证据检索（BM25 + e5）", "evidence retrieval (BM25 + e5)"),
    "scope-mahalanobis-v1": ("范围检测（马氏距离）", "scope detection (Mahalanobis)"),
    "intent-tfidf-lr-v1": ("提问意图（TF-IDF + LR）", "question intent (TF-IDF + LR)"),
    "behavior-v1": ("行为识别（DTW / HMM）", "behaviour recognition (DTW / HMM)"),
    "relation-stack-v1": ("关系判定堆叠集成", "relation stacked ensemble"),
}
FALLBACK_REASONS = {
    "not_configured": ("未设 CAREER_LAB_RECOGNIZERS", "CAREER_LAB_RECOGNIZERS not set"),
    "missing": ("权重目录不在", "weight directory missing"),
    "hash_mismatch": ("权重与登记的哈希不一致", "weights do not match the manifest hash"),
}
CODE_REASONS = {
    "unknown_code": (
        "库里没有这个码（码被换过，或换了库、换了凭据密钥）",
        "not in this database (replaced, or the database or key changed)",
    ),
    "key_changed": ("凭据密钥换过，码已失效", "credential key changed"),
    "scenario_missing": ("这局的场景不在当前目录里", "scenario not installed"),
    "no_key": ("没有凭据密钥", "no credential key"),
}


def probe(command: list[str], env: dict[str, str], timeout: float) -> dict:
    try:
        result = subprocess.run(
            [str(venv_bin("python")), "-m", "scripts.demo.probe", *command],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"error": "probe_failed"}


def cmd_check(args) -> int:
    run_dir = args.run_dir
    state = read_state(run_dir)
    findings: list[dict] = []

    def add(section: str, level: str, text: str) -> None:
        findings.append({"section": section, "level": level, "text": text})

    if not state or not state.get("pids"):
        add("services", "block", t("没有由 up 启动的运行环境", "no environment started by up"))
        return report(args, state, findings)
    # The configuration the services started with (secret values are not kept, and no probe
    # needs one), not whatever this shell happens to export now.
    configuration = {k: v for k, v in state.get("env", {}).items() if v != "(set)"}
    if state.get("env_file") and Path(state["env_file"]).is_file():
        configuration.update(parse_env_file(Path(state["env_file"]).read_text(encoding="utf-8"))[0])
    env = deployment_env(run_dir, configuration)
    urls = state["urls"]

    # Services
    status, body = http_get(urls["api"] + "/health")
    if status == 200:
        add("services", "ok", "API " + urls["api"] + t(" 运行中", " running"))
    else:
        add("services", "block", "API " + urls["api"] + t(" 没有响应", " not responding"))
    workers = [n for n in state["pids"] if n.startswith("worker")]
    alive = [n for n in workers if pid_alive(state["pids"][n])]
    level = "ok" if workers and len(alive) == len(workers) else "block"
    add("services", level, f"worker {len(alive)}/{len(workers)}" + t(" 运行中", " running"))
    page_status, page = http_get(urls["web"] + "/")
    proxied = http_get(urls["web"] + "/api/health")[0]
    if page_status == 200 and proxied == 200:
        add(
            "services",
            "ok",
            t("前端 ", "frontend ") + urls["web"] + t("，/api 代理通", ", /api ok"),
        )
    else:
        add(
            "services",
            "block",
            t("前端或 /api 代理不通 ", "frontend or /api proxy down ") + urls["web"],
        )

    # Frontend build
    stamp_file = run_dir / "web-build.json"
    stamp = json.loads(stamp_file.read_text()) if stamp_file.is_file() else {}
    if stamp.get("source") != tree_fingerprint(WEB, web_sources()):
        add("web", "block", t("前端源码在构建后改过：重新 up", "sources changed since the build"))
    elif stamp.get("dist") != dist_fingerprint():
        add("web", "block", t("dist 被别处重建过：重新 up", "dist was rebuilt elsewhere"))
    else:
        add(
            "web",
            "ok",
            t("页面是当前源码的构建", "build matches the sources")
            + t(f"（{stamp['head']}）", f" ({stamp['head']})"),
        )
    params = {
        "index.html": engine_param((WEB / "index.html").read_text("utf-8")),
        "dist": engine_param((WEB / "dist/index.html").read_text("utf-8"))
        if (WEB / "dist/index.html").is_file()
        else None,
        t("页面", "served"): engine_param(page.decode("utf-8", "replace")) if page else None,
    }
    engine = (WEB / "public/workbench-engine.js").read_bytes()
    served = http_get(f"{urls['web']}/workbench-engine.js?v={params['index.html']}")[1]
    if len(set(params.values())) == 1 and served == engine:
        add(
            "web", "ok", f"workbench-engine.js?v={params['index.html']}" + t(" 一致", " consistent")
        )
    else:
        shown = ", ".join(f"{k}={v}" for k, v in params.items())
        add("web", "block", t("缓存参数或引擎文件不一致：", "engine version mismatch: ") + shown)
    if (
        stamp.get("previous_engine")
        and stamp.get("previous_engine") != stamp.get("engine_sha256")
        and stamp.get("previous_param") == stamp.get("engine_param")
    ):
        add(
            "web",
            "warn",
            t(
                "workbench-engine.js 改过但 ?v= 没改，旧浏览器可能用缓存",
                "workbench-engine.js changed but ?v= did not; browsers may cache it",
            ),
        )

    # Scenarios
    catalog = json.loads((run_dir / "catalog.json").read_text(encoding="utf-8"))["scenarios"]
    ids = []
    for entry in catalog:
        manifest = json.loads((Path(entry["root"]) / "manifest.json").read_text("utf-8"))
        ids.append((manifest.get("id", "?"), entry["work_language"]))
    languages = sorted({language for _, language in ids})
    names = sorted({name for name, _ in ids})
    add(
        "scenarios",
        "ok",
        f"{len(ids)} "
        + t("个场景包：", "packages: ")
        + f"{', '.join(names)} · {'/'.join(languages)}",
    )

    # Models and recognizers, as the worker reported them at startup
    worker = parse_worker_log(tail(run_dir / "logs/worker-1.log", 400))
    for slot in SLOTS:
        info = worker["slots"].get(slot)
        use = t(*SLOT_USE[slot])
        if info is None:
            add(
                "models",
                "block",
                f"{slot} {use}" + t("：", ": ") + t("worker 没有报告", "not reported"),
            )
        elif info["provider"] == "local":
            add(
                "models",
                "replay",
                f"{slot} {use}"
                + t("：", ": ")
                + "local — "
                + t("界面会显示「等待模型接入」", "shows 'waiting for model'"),
            )
        else:
            add(
                "models",
                "ok",
                f"{slot} {use}" + t("：", ": ") + f"{info['provider']} · {info['model']}",
            )
    if any(info.get("provider") not in (None, "local") for info in worker["slots"].values()):
        add(
            "models",
            "warn",
            t(
                "只核对了配置，没有调用模型验证 key；录前在界面里问一次同事、测一次助手",
                "configuration only: no model was called to test the key; try one reply first",
            ),
        )
    for rid in RECOGNIZERS:
        info = worker["recognizers"].get(rid)
        name = t(*RECOGNIZER_NAMES[rid])
        if info and info["loaded"]:
            add(
                "recognizers",
                "ok",
                name + t("：", ": ") + t("已加载 ", "loaded ") + info["revision"],
            )
        else:
            reason = (info or {}).get("reason", "not_configured")
            text = t(*FALLBACK_REASONS.get(reason, (reason, reason)))
            add(
                "recognizers",
                "replay",
                name + t("：", ": ") + t("规则回退（", "rule fallback (") + text + t("）", ")"),
            )
    encoder_name = t("关系判定编码器（XLM-R）", "relation encoder (XLM-R)")
    if not env.get("CAREER_LAB_RELATION_ENCODER"):
        add(
            "recognizers",
            "replay",
            encoder_name
            + t("：", ": ")
            + t("未设 CAREER_LAB_RELATION_ENCODER", "CAREER_LAB_RELATION_ENCODER not set"),
        )
    elif getattr(args, "no_encoder_load", False):
        add(
            "recognizers",
            "warn",
            encoder_name + t("：", ": ") + t("已配置，未试加载", "configured, not loaded here"),
        )
    else:
        loaded = probe(["encoder"], env, 240)
        if loaded.get("ok"):
            extra = (
                t("，堆叠集成匹配", ", stack matches")
                if loaded.get("stack")
                else t("，堆叠集成与它不匹配", ", stack does not match")
            )
            add(
                "recognizers",
                "ok" if loaded.get("stack") else "replay",
                encoder_name + t("：", ": ") + t("已加载 ", "loaded ") + loaded["revision"] + extra,
            )
        else:
            if loaded.get("reason") == "missing_module":
                reason = t(
                    f"缺少 Python 包 {loaded.get('module')}，重新 up 会装 encoder 依赖",
                    f"Python package {loaded.get('module')} missing; up installs it",
                )
            elif loaded.get("reason") == "missing":
                reason = t("目录不在", "directory missing")
            else:
                reason = str(loaded.get("reason") or loaded.get("error"))
            add(
                "recognizers",
                "replay",
                encoder_name
                + t("：", ": ")
                + t("加载失败（", "failed to load (")
                + reason
                + t("）", ")"),
            )

    registered = probe(["registrations"], env, 60)
    if not registered.get("configured"):
        add(
            "advice",
            "warn",
            t(
                "评审页逐句模型建议未登记（CAREER_LAB_MODEL_REGISTRY）："
                "新交付没有这一块，演示包里存下的照常显示",
                "review-page model advice not registered (CAREER_LAB_MODEL_REGISTRY): "
                "new submissions omit it; recorded ones still show",
            ),
        )
    elif registered.get("ok"):
        add(
            "advice",
            "ok",
            t("评审页模型建议已登记：", "model advice registered: ")
            + ", ".join(registered.get("tasks", {})),
        )
    else:
        add(
            "advice",
            "replay",
            t("模型建议登记有问题：", "model advice registration problem: ")
            + json.dumps(registered.get("tasks") or registered.get("reason")),
        )

    # Continue codes
    codes_file = run_dir / "continue-codes.json"
    if codes_file.is_file():
        checked = probe(
            ["codes", "--db", str(run_dir / "rolecraft.db"), "--codes", str(codes_file)]
            + ["--catalog", str(run_dir / "catalog.json")],
            env,
            60,
        ).get("codes", [])
        good = [c for c in checked if c.get("ok")]
        level = "ok" if checked and len(good) == len(checked) else "block"
        add(
            "codes",
            level,
            t(
                f"演示包继续码 {len(good)}/{len(checked)} 可用",
                f"demo continue codes {len(good)}/{len(checked)} usable",
            ),
        )
        for entry in checked:
            if not entry.get("ok"):
                reason = t(*CODE_REASONS.get(entry["reason"], (entry["reason"],) * 2))
                add("codes", "block", f"  {entry['label']}" + t("：", ": ") + reason)
    else:
        add("codes", "warn", t("没有导入演示包", "demo pack not imported"))
    return report(args, state, findings)


SECTIONS = {
    "services": ("服务", "Services"),
    "web": ("前端版本", "Frontend build"),
    "scenarios": ("场景", "Scenarios"),
    "models": ("模型槽（worker 启动时）", "Model slots (worker at startup)"),
    "recognizers": ("识别器（worker 启动时）", "Recognizers (worker at startup)"),
    "advice": ("评审页模型建议", "Review-page model advice"),
    "codes": ("演示包", "Demo pack"),
}
MARKS = {"ok": "✓", "warn": "!", "replay": "○", "block": "✗"}


def report(args, state: dict | None, findings: list[dict]) -> int:
    outcome = verdict(findings)
    if getattr(args, "json", False):
        print(json.dumps({"verdict": outcome, "findings": findings}, ensure_ascii=False, indent=2))
        return {"full": 0, "replay": 1, "blocked": 2}[outcome]
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(t("RoleCraft 录前自检", "RoleCraft pre-recording check") + f" · {stamp} · {args.run_dir}")
    for section, names in SECTIONS.items():
        rows = [f for f in findings if f["section"] == section]
        if not rows:
            continue
        print("\n" + t(*names))
        for row in rows:
            print(f"  {MARKS[row['level']]} {row['text']}")
    print()
    if outcome == "full":
        print(t("结论：能录完整系统。", "Verdict: ready to record the full system."))
    elif outcome == "replay":
        print(
            t(
                "结论：只适合录演示包回放。标 ○ 的项会在画面上显示规则回退或「等待模型接入」；"
                "要录完整系统，按 docs/RUN-DEMO.md 补权重与模型配置后重新 up。",
                "Verdict: fit for replaying the demo pack only. Items marked ○ show rule fallback "
                "or 'waiting for model'; see docs/RUN-DEMO.md, then run up again.",
            )
        )
    else:
        print(
            t("结论：现在不能录，先处理标 ✗ 的项。", "Verdict: not ready; fix the items marked ✗.")
        )
    return {"full": 0, "replay": 1, "blocked": 2}[outcome]


# ---------------------------------------------------------------- entry


def default_language() -> str:
    chosen = os.environ.get("ROLECRAFT_DEMO_LANG")
    if chosen in ("zh", "en"):
        return chosen
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if os.environ.get(name):
            return "zh" if os.environ[name].lower().startswith("zh") else "en"
    try:
        current = locale.getlocale()[0] or ""
    except ValueError:
        current = ""
    return "zh" if current.lower().startswith("zh") else "en"


def main(argv=None) -> int:
    global LANG
    parser = argparse.ArgumentParser(
        prog="scripts/demo/launcher.py", description=__doc__.split("\n\n")[0]
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--run-dir",
        type=Path,
        default=REPO / "runs/demo-stack",
        help="database, key, logs and codes (default runs/demo-stack)",
    )
    common.add_argument("--lang", choices=["zh", "en"], default=None, help="output language")
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("up", parents=[common], help="start API, worker and frontend")
    up.add_argument("--host", default="127.0.0.1")
    up.add_argument("--api-port", type=int, default=18562)
    up.add_argument("--web-port", type=int, default=18560)
    up.add_argument(
        "--provider", choices=["local", "deepseek", "openai", "openai_compatible"], default="local"
    )
    up.add_argument("--env-file", type=Path, help="CAREER_LAB_* paths and providers, no keys")
    up.add_argument("--encoder", action="store_true", help="install torch (uv --extra encoder)")
    up.add_argument("--catalog", choices=sorted(CATALOGS), default="demo")
    up.add_argument("--no-demo-pack", action="store_true")
    up.add_argument("--reimport", action="store_true", help="replace demo sessions, new codes")
    up.add_argument("--workers", type=int, default=1)
    up.add_argument("--no-encoder-load", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("down", parents=[common], help="stop what up started")
    sub.add_parser("status", parents=[common], help="processes, address and continue codes")
    check = sub.add_parser("check", parents=[common], help="is this environment fit to record?")
    check.add_argument("--json", action="store_true")
    check.add_argument("--no-encoder-load", action="store_true")
    args = parser.parse_args(argv)
    LANG = args.lang or default_language()
    args.run_dir = args.run_dir if args.run_dir.is_absolute() else Path.cwd() / args.run_dir
    os.chdir(REPO)
    handler = {"up": cmd_up, "down": cmd_down, "status": cmd_status, "check": cmd_check}
    return handler[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
