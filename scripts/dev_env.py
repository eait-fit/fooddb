"""This worktree's ports, databases and env file, derived from ONE number: its slot.

    python scripts/dev_env.py setup          derive (or re-derive) and write .env.worktree
    python scripts/dev_env.py show           print the derivation
    python scripts/dev_env.py derived-keys   the keys this owns, for dev.sh to unset
    python scripts/dev_env.py branch-check   warn when .env.worktree names another branch
    python scripts/dev_env.py ls             every worktree, its slot and what it runs
    python scripts/dev_env.py clean          give this worktree's slot back

Ported from eait's src/scripts/dev-env.ts. Same rules:

- The MAIN worktree is slot 0. A linked worktree claims the lowest free slot and remembers it in
  `.fooddb-slot`, so a slot never moves under a running stack.
- Ports step by 10 per slot from 9640. eait's ladders (8484+10N, 8787+10N and friends) are far
  below, so no slot here meets one of theirs.
- One shared Postgres serves every worktree. Each worktree gets its own database, named after its
  branch, plus a `__test` twin. The DOUBLE underscore keeps them apart: a branch name cannot
  produce one, so no branch's dev database is another branch's test database.
- The database name is fixed when first derived and NOT re-derived on `git switch`; branch-check
  warns instead, because renaming a database under a running worker loses its data.

Stdlib only: this runs before `uv sync` has.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

PORT_BASE = 9640
PORT_STEP = 10
PG_BASE_URL = os.environ.get("FOODDB_PG_BASE_URL", "postgresql://fooddb:fooddb@127.0.0.1:5440")
SLOT_FILE = ".fooddb-slot"
ENV_FILE = ".env.worktree"
DERIVED_KEYS = [
    "FOODDB_SLOT", "FOODDB_BRANCH", "FOODDB__BACKEND__API_PORT", "FOODDB_API_URL", "FOODDB_DB_NAME",
    "FOODDB__BACKEND__DATABASE_URL", "FOODDB_TEST_DB_NAME", "FOODDB_TEST_DATABASE_URL",
]
ROOT = Path(__file__).resolve().parents[1]


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def worktrees() -> list[tuple[Path, str]]:
    """(path, branch) in git's order; the first is the main worktree."""
    out, path = [], None
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = Path(line.split(" ", 1)[1]).resolve()
            out.append((path, ""))
        elif line.startswith("branch ") and path is not None:
            out[-1] = (path, line.split("refs/heads/", 1)[-1])
    return out


def current_branch() -> str:
    return git("rev-parse", "--abbrev-ref", "HEAD").strip()


def claim_of(path: Path) -> int | None:
    try:
        return int((path / SLOT_FILE).read_text().strip())
    except (OSError, ValueError):
        return None


def slot() -> int:
    pinned = os.environ.get("FOODDB_WORKTREE_SLOT")
    if pinned:
        return int(pinned)
    trees = worktrees()
    if ROOT == trees[0][0]:
        return 0
    if (mine := claim_of(ROOT)) is not None:
        return mine
    taken = {claim_of(p) for p, _ in trees[1:] if p != ROOT} | {0}
    n = next(i for i in range(1, 1000) if i not in taken)
    (ROOT / SLOT_FILE).write_text(f"{n}\n")
    return n


def db_name_for(n: int, branch: str) -> str:
    if n == 0:
        return "fooddb"
    cleaned = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", branch.lower())).strip("_")
    return f"fooddb_{cleaned or n}"[:55]


def test_db_name_for(name: str) -> str:
    return f"{name[:55]}__test"


def derive() -> dict[str, str]:
    n, branch = slot(), current_branch()
    existing = read_env()
    # Fixed at first derivation: a `git switch` does not rename the database (see branch-check).
    name = existing.get("FOODDB_DB_NAME") or db_name_for(n, branch)
    port = PORT_BASE + PORT_STEP * n
    return {
        "FOODDB_SLOT": str(n),
        "FOODDB_BRANCH": existing.get("FOODDB_BRANCH") or branch,
        "FOODDB__BACKEND__API_PORT": str(port),
        "FOODDB_API_URL": f"http://127.0.0.1:{port}",
        "FOODDB_DB_NAME": name,
        "FOODDB__BACKEND__DATABASE_URL": f"{PG_BASE_URL}/{name}",
        "FOODDB_TEST_DB_NAME": test_db_name_for(name),
        "FOODDB_TEST_DATABASE_URL": f"{PG_BASE_URL}/{test_db_name_for(name)}",
    }


def read_env(root: Path = ROOT) -> dict[str, str]:
    try:
        lines = (root / ENV_FILE).read_text().splitlines()
    except OSError:
        return {}
    return dict(l.split("=", 1) for l in lines if "=" in l and not l.startswith("#"))


def safe(values: dict[str, str]) -> None:
    """Refuse a derivation that would share a database with another worktree, or carry a name that
    is not safe to put into SQL (db.sh quotes it, and a hand-edited .env.worktree reaches it)."""
    for key in ("FOODDB_DB_NAME", "FOODDB_TEST_DB_NAME"):
        if not re.fullmatch(r"[a-z0-9_]{1,63}", values[key]):
            raise SystemExit(f"dev-env: {key}={values[key]!r} is not a safe database name ([a-z0-9_])")
    if values["FOODDB_DB_NAME"] == values["FOODDB_TEST_DB_NAME"]:
        raise SystemExit("dev-env: dev and test database names collide")
    for path, _ in worktrees():
        if path == ROOT:
            continue
        other = read_env(path)
        if other.get("FOODDB_DB_NAME") in (values["FOODDB_DB_NAME"], values["FOODDB_TEST_DB_NAME"]):
            raise SystemExit(f"dev-env: database {other['FOODDB_DB_NAME']} already belongs to {path}")
        if other.get("FOODDB__BACKEND__API_PORT") == values["FOODDB__BACKEND__API_PORT"]:
            raise SystemExit(f"dev-env: port {values['FOODDB__BACKEND__API_PORT']} already belongs to {path}")


def setup() -> None:
    values = derive()
    safe(values)
    body = "# Derived by scripts/dev_env.py. Re-run `./dev env setup` rather than editing.\n"
    body += "".join(f"{k}={v}\n" for k, v in values.items())
    (ROOT / ENV_FILE).write_text(body)
    show(values)


def show(values: dict[str, str] | None = None) -> None:
    for k, v in (values or derive()).items():
        print(f"{k}={v}")


def branch_check() -> int:
    recorded, now = read_env().get("FOODDB_BRANCH"), current_branch()
    if recorded and recorded != now:
        print(f"dev-env: this worktree was derived on branch {recorded!r}, now on {now!r}. "
              f"The database keeps its name ({read_env().get('FOODDB_DB_NAME')}); "
              "`./dev env clean && ./dev env setup` gives it a new one.", file=sys.stderr)
    return 0


def running(path: Path) -> list[str]:
    out = []
    for pidfile in sorted((path / ".dev").glob("*.pid")):
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)
        except (OSError, ValueError):
            continue
        out.append(pidfile.stem)
    return out


def ls(plain: bool) -> None:
    rows = []
    for path, branch in worktrees():
        env = read_env(path)
        n = env.get("FOODDB_SLOT", "0" if path == worktrees()[0][0] else "-")
        rows.append((n, branch or "(detached)", env.get("FOODDB__BACKEND__API_PORT", "-"),
                     env.get("FOODDB_DB_NAME", "-"), ",".join(running(path)) or "-", str(path)))
    if plain:
        for r in rows:
            print("\t".join(r))
        return
    head = ("slot", "branch", "api", "database", "running", "path")
    widths = [max(len(x) for x in col) for col in zip(head, *rows)]
    for r in (head, *rows):
        print("  ".join(x.ljust(w) for x, w in zip(r, widths)))


def clean() -> None:
    for f in (SLOT_FILE, ENV_FILE):
        (ROOT / f).unlink(missing_ok=True)
    print("dev-env: slot and env file removed (the databases stay; `./dev db drop` removes them)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    match cmd:
        case "setup": setup()
        case "show": show()
        case "derived-keys": print(" ".join(DERIVED_KEYS))
        case "branch-check": sys.exit(branch_check())
        case "ls": ls("--plain" in sys.argv)
        case "clean": clean()
        case _: sys.exit(f"dev-env: unknown command {cmd!r}")
