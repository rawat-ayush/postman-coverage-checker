"""Tkinter GUI for the Postman coverage checker."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from dotenv import load_dotenv

from .config import AppConfig, CoreConfig, load_config
from .coverage import check_core
from .github_client import GithubClient
from .matcher import MatchResult, MatchTier, Matcher, sub_is_type_covered
from .postman_client import PostmanClient
from .report import CoreReport, write_report

def _candidate_roots() -> list[Path]:
    """Directories to search for the default config / reports folder.

    We try (in order): the current working directory, the installed package's
    project root (walking up from this file until we find a `config/` dir),
    and the parents of that project root. This lets `postman-coverage-gui`
    work regardless of where the user launches it from.
    """
    roots: list[Path] = [Path.cwd()]
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config").is_dir() or (parent / "pyproject.toml").is_file():
            roots.append(parent)
            break
    seen: set[Path] = set()
    unique: list[Path] = []
    for r in roots:
        rp = r.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(rp)
    return unique


def _pick_default_config() -> Path:
    names = ("cores.local.yaml", "cores.defaults.yaml", "cores.yaml")
    for root in _candidate_roots():
        for name in names:
            candidate = root / "config" / name
            if candidate.exists():
                return candidate
    # Fall back to a sensible absolute path even if it doesn't exist yet.
    return _candidate_roots()[0] / "config" / "cores.yaml"


def _pick_default_reports() -> Path:
    """Default reports folder: `<user home>/Downloads/postman-coverage/`.

    Falls back to a workspace-local `reports/` folder if a home directory
    can't be resolved.
    """
    try:
        downloads = Path.home() / "Downloads"
        if downloads.is_dir():
            return downloads / "postman-coverage"
    except Exception:  # noqa: BLE001
        pass
    return _candidate_roots()[0] / "reports"


_DEFAULT_CONFIG = _pick_default_config()
_DEFAULT_REPORTS = _pick_default_reports()

# Background colors for treeview status tags.
_TAG_COLORS = {
    "covered": "#e6f4ea",   # soft green
    "partial": "#fff5cc",   # soft yellow
    "missing": "#ffe0e0",   # soft red
}


class CoverageApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Postman Coverage Checker")
        self.geometry("1150x760")
        self.minsize(900, 600)

        self._cfg: AppConfig | None = None
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None

        self._build_ui()
        self._poll_log_queue()

        # Auto-load the default config so the Core dropdown is populated
        # without requiring the user to visit the Config tab first.
        self.after(50, self._auto_load_config)

    # ---- UI construction -------------------------------------------------
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        load_dotenv()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=(6, 0))

        work_tab = ttk.Frame(nb)
        config_tab = ttk.Frame(nb)
        nb.add(work_tab, text="Work")
        nb.add(config_tab, text="Config")

        self._build_config_tab(config_tab, pad)
        self._build_work_tab(work_tab, pad)

        self.status_var = tk.StringVar(value="Load a config to begin.")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(
            fill="x", padx=8, pady=(0, 6)
        )

    def _build_config_tab(self, parent: ttk.Frame, pad: dict) -> None:
        paths = ttk.LabelFrame(parent, text="Paths")
        paths.pack(fill="x", **pad)

        ttk.Label(paths, text="Config file:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.config_var = tk.StringVar(value=str(_DEFAULT_CONFIG))
        ttk.Entry(paths, textvariable=self.config_var, width=60).grid(
            row=0, column=1, sticky="ew", padx=4, pady=2
        )
        ttk.Button(paths, text="Browse...", command=self._pick_config).grid(row=0, column=2, padx=2)
        ttk.Button(paths, text="Load", command=self._load_config).grid(row=0, column=3, padx=4)

        ttk.Label(paths, text="Reports dir:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.reports_var = tk.StringVar(value=str(_DEFAULT_REPORTS))
        ttk.Entry(paths, textvariable=self.reports_var, width=60).grid(
            row=1, column=1, sticky="ew", padx=4, pady=2
        )
        ttk.Button(paths, text="Browse...", command=self._pick_reports_dir).grid(row=1, column=2, padx=2)

        paths.columnconfigure(1, weight=1)

        creds = ttk.LabelFrame(parent, text="Credentials")
        creds.pack(fill="x", **pad)

        ttk.Label(creds, text="GitHub PAT:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.gh_token_var = tk.StringVar(value=os.getenv("GITHUB_TOKEN", ""))
        self.gh_entry = ttk.Entry(creds, textvariable=self.gh_token_var, show="*", width=50)
        self.gh_entry.grid(row=0, column=1, sticky="ew", padx=4, pady=2)
        self.show_gh_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            creds, text="Show", variable=self.show_gh_var,
            command=lambda: self.gh_entry.configure(show="" if self.show_gh_var.get() else "*"),
        ).grid(row=0, column=2, padx=4)

        ttk.Label(creds, text="Postman API key:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.pm_key_var = tk.StringVar(value=os.getenv("POSTMAN_API_KEY", ""))
        self.pm_entry = ttk.Entry(creds, textvariable=self.pm_key_var, show="*", width=50)
        self.pm_entry.grid(row=1, column=1, sticky="ew", padx=4, pady=2)
        self.show_pm_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            creds, text="Show", variable=self.show_pm_var,
            command=lambda: self.pm_entry.configure(show="" if self.show_pm_var.get() else "*"),
        ).grid(row=1, column=2, padx=4)

        ttk.Label(creds, text="Postman workspace ID:").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        self.pm_ws_var = tk.StringVar(value=os.getenv("POSTMAN_WORKSPACE_ID", ""))
        ttk.Entry(creds, textvariable=self.pm_ws_var, width=50).grid(
            row=2, column=1, sticky="ew", padx=4, pady=2
        )

        creds.columnconfigure(1, weight=1)

        ttk.Label(
            parent,
            text=(
                "Tip: credentials can also live in the config file under "
                "`github.token` / `postman.api_key`, or in a .env file. "
                "Values entered here override both."
            ),
            wraplength=780,
            foreground="#555",
        ).pack(fill="x", padx=12, pady=(4, 0))

    def _build_work_tab(self, parent: ttk.Frame, pad: dict) -> None:
        help_box = ttk.LabelFrame(parent, text="How to use")
        help_box.pack(fill="x", **pad)
        ttk.Label(
            help_box,
            justify="left",
            wraplength=820,
            text=(
                "1. Config tab: confirm the config path and credentials, click Load.\n"
                "2. Pick a core from the dropdown, or tick 'Run all cores'.\n"
                "3. Click Run. Rows appear per domain with covered / partial / "
                "missing counts, plus a TOTAL row per core. Full details of each "
                "missing / partial YAML (with fuzzy suggestions and per-type "
                "breakdown) are written to the JSON report in the reports/ folder."
            ),
        ).pack(fill="x", padx=8, pady=6)

        mid = ttk.Frame(parent)
        mid.pack(fill="x", **pad)

        ttk.Label(mid, text="Core:").grid(row=0, column=0, sticky="w")
        self.core_var = tk.StringVar()
        self.core_combo = ttk.Combobox(
            mid, textvariable=self.core_var, state="readonly", width=40
        )
        self.core_combo.grid(row=0, column=1, sticky="w", padx=4)

        self.all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            mid, text="Run all cores", variable=self.all_var, command=self._toggle_all
        ).grid(row=0, column=2, padx=8)

        self.run_btn = ttk.Button(mid, text="Run", command=self._run)
        self.run_btn.grid(row=0, column=3, padx=8)

        self.discover_btn = ttk.Button(
            mid, text="Discover reference tree", command=self._discover
        )
        self.discover_btn.grid(row=0, column=4, padx=8)

        # --- Results tree ---------------------------------------------------
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill="both", expand=True, **pad)

        controls = ttk.Frame(tree_frame)
        controls.pack(fill="x")
        ttk.Label(controls, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(controls, textvariable=self.filter_var, width=40).pack(
            side="left", padx=(4, 12)
        )
        ttk.Button(
            controls, text="Expand issues", command=self._expand_issues
        ).pack(side="left", padx=2)
        ttk.Button(
            controls, text="Collapse all", command=self._collapse_all
        ).pack(side="left", padx=2)
        ttk.Button(
            controls, text="Open report file", command=self._open_selected_report
        ).pack(side="left", padx=2)

        legend = ttk.Frame(tree_frame)
        legend.pack(fill="x", pady=(4, 0))
        ttk.Label(legend, text="Legend:").pack(side="left")
        for label, tag in (("Covered", "covered"), ("Partial", "partial"), ("Missing", "missing")):
            swatch = tk.Label(legend, text=" " + label + " ", bg=_TAG_COLORS[tag])
            swatch.pack(side="left", padx=3)

        cols = ("yaml", "covered", "partial", "missing", "detail")
        self.tree = ttk.Treeview(
            tree_frame, columns=cols, show="tree headings", height=16
        )
        self.tree.heading("#0", text="Item")
        self.tree.column("#0", width=340, anchor="w")
        widths = (60, 80, 70, 80, 500)
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=w, anchor="w")

        for tag, color in _TAG_COLORS.items():
            self.tree.tag_configure(tag, background=color)
        self.tree.tag_configure("core", font=("TkDefaultFont", 10, "bold"))
        self.tree.tag_configure("domain", font=("TkDefaultFont", 9, "bold"))

        yscroll_tree = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll_tree.set)
        self.tree.pack(side="left", fill="both", expand=True, pady=(4, 0))
        yscroll_tree.pack(side="right", fill="y", pady=(4, 0))

        # Map from tree item id -> report path, so we can open it on demand.
        self._item_report: dict[str, str] = {}
        # Cache the detached items for the filter feature.
        self._all_children: dict[str, list[tuple[str, int]]] = {}

        log_frame = ttk.LabelFrame(parent, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        yscroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=yscroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

    # ---- Event handlers --------------------------------------------------
    def _pick_config(self) -> None:
        path = filedialog.askopenfilename(
            title="Select cores.yaml",
            filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")],
        )
        if path:
            self.config_var.set(path)

    def _pick_reports_dir(self) -> None:
        path = filedialog.askdirectory(title="Select reports directory")
        if path:
            self.reports_var.set(path)

    def _load_config(self) -> None:
        try:
            cfg = load_config(
                Path(self.config_var.get()),
                github_token=self.gh_token_var.get().strip() or None,
                postman_api_key=self.pm_key_var.get().strip() or None,
                postman_workspace_id=self.pm_ws_var.get().strip() or None,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Config error", str(exc))
            self.status_var.set(f"Config error: {exc}")
            return
        self._apply_loaded_config(cfg)

    def _auto_load_config(self) -> None:
        """Load the default config at startup without popping error dialogs."""
        path = Path(self.config_var.get())
        if not path.exists():
            self.status_var.set(
                f"No default config at {path}. Pick one on the Config tab and click Load."
            )
            self._append_log(
                f"Startup: default config not found at {path}. "
                "Use the Config tab to select a cores.yaml and click Load.\n"
            )
            return
        try:
            cfg = load_config(
                path,
                github_token=self.gh_token_var.get().strip() or None,
                postman_api_key=self.pm_key_var.get().strip() or None,
                postman_workspace_id=self.pm_ws_var.get().strip() or None,
            )
        except Exception as exc:  # noqa: BLE001
            # Still try to populate the dropdown from the file so the user
            # can see the cores even if credentials aren't ready yet.
            self._populate_cores_from_file(path)
            self.status_var.set(f"Loaded cores from {path.name}, but: {exc}")
            self._append_log(
                f"Startup: loaded core list from {path}, but credentials are "
                f"missing: {exc}\nFill them in on the Config tab and click Load.\n"
            )
            return
        self._apply_loaded_config(cfg)

    def _apply_loaded_config(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        codes = sorted(cfg.cores.keys())
        self.core_combo["values"] = codes
        if codes and not self.core_var.get():
            self.core_var.set(codes[0])
        # Reflect the resolved credentials back into the entry fields so the
        # user can see what actually loaded (from yaml, env, or manual entry).
        self.gh_token_var.set(cfg.github_token)
        self.pm_key_var.set(cfg.postman_api_key)
        self.pm_ws_var.set(cfg.postman_workspace_id)
        self.status_var.set(f"Loaded {len(codes)} cores from {self.config_var.get()}")
        self._append_log(f"Loaded config: {len(codes)} cores -> {', '.join(codes)}\n")

    def _populate_cores_from_file(self, path: Path) -> None:
        """Fill just the core dropdown from a YAML file, ignoring credentials."""
        try:
            from .config import _read_and_merge  # local import to avoid cycles

            raw = _read_and_merge(path)
            codes = sorted((raw.get("cores") or {}).keys(), key=str.upper)
            self.core_combo["values"] = [c.upper() for c in codes]
            if codes:
                self.core_var.set(codes[0].upper())
        except Exception:  # noqa: BLE001
            pass

    def _toggle_all(self) -> None:
        state = "disabled" if self.all_var.get() else "readonly"
        self.core_combo.configure(state=state)

    def _run(self) -> None:
        if self._cfg is None:
            messagebox.showwarning("No config", "Load a config file first.")
            return
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("Busy", "A run is already in progress.")
            return

        cores: list[CoreConfig]
        if self.all_var.get():
            cores = list(self._cfg.cores.values())
        else:
            code = self.core_var.get().strip()
            core = self._cfg.resolve_core(code) if code else None
            if core is None:
                messagebox.showwarning("No core", "Select a core or check 'Run all cores'.")
                return
            cores = [core]

        for row in self.tree.get_children():
            self.tree.delete(row)
        self._item_report.clear()
        self._all_children.clear()

        reports_dir = Path(self.reports_var.get())
        self.run_btn.configure(state="disabled")
        self.discover_btn.configure(state="disabled")
        self.status_var.set("Running...")
        self._append_log(f"\n=== Run: {[c.code for c in cores]} ===\n")

        self._worker = threading.Thread(
            target=self._run_worker,
            args=(cores, reports_dir),
            daemon=True,
        )
        self._worker.start()

    # ---- Worker ----------------------------------------------------------
    def _run_worker(self, cores: list[CoreConfig], reports_dir: Path) -> None:
        assert self._cfg is not None
        cfg = self._cfg
        matcher = Matcher(
            service_subject_map=cfg.service_subject_map,
            action_synonyms=cfg.action_synonyms,
            type_synonyms=cfg.type_synonyms,
            suggestion_min_score=cfg.suggestion_min_score,
        )
        gh = GithubClient(cfg.github_token)
        pm = PostmanClient(cfg.postman_api_key)

        for core in cores:
            try:
                self._log(f"[{core.code}] fetching YAMLs and collection...\n")
                report = check_core(core, cfg, gh, pm, matcher, log=self._log)
                out_path = write_report(report, reports_dir)
                self._log(
                    f"[{core.code}] domains={len(report.domains)} "
                    f"yaml={report.total_yaml} covered={report.covered} "
                    f"partial={report.partial} missing={report.missing} "
                    f"unparseable={len(report.unparseable_files)} -> {out_path}\n"
                )
                self.after(0, lambda r=report, p=str(out_path): self._display_report(r, p))
            except Exception as exc:  # noqa: BLE001
                self._log(f"[{core.code}] FAILED: {exc}\n")
                self.after(0, lambda code=core.code, msg=str(exc): self._display_failure(code, msg))

        self._log("=== Done ===\n")
        self.after(0, self._finish_run)

    def _finish_run(self) -> None:
        self.run_btn.configure(state="normal")
        self.discover_btn.configure(state="normal")
        self.status_var.set("Done.")

    # ---- Discover reference tree ---------------------------------------
    def _discover(self) -> None:
        if self._cfg is None:
            messagebox.showwarning("No config", "Load a config file first.")
            return
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("Busy", "A job is already in progress.")
            return

        cores: list[CoreConfig]
        if self.all_var.get():
            cores = list(self._cfg.cores.values())
        else:
            code = self.core_var.get().strip()
            core = self._cfg.resolve_core(code) if code else None
            if core is None:
                messagebox.showwarning("No core", "Select a core or check 'Run all cores'.")
                return
            cores = [core]

        self.discover_btn.configure(state="disabled")
        self.run_btn.configure(state="disabled")
        self.status_var.set("Discovering...")
        self._append_log(f"\n=== Discover reference/ tree: {[c.code for c in cores]} ===\n")

        self._worker = threading.Thread(
            target=self._discover_worker, args=(cores,), daemon=True
        )
        self._worker.start()

    def _discover_worker(self, cores: list[CoreConfig]) -> None:
        assert self._cfg is not None
        gh = GithubClient(self._cfg.github_token)

        # Deduplicate by (owner, repo, branch, parent-of-path) so we list each
        # `reference/` root only once, then descend into each core.
        seen_roots: set[tuple[str, str, str, str]] = set()
        for core in cores:
            g = core.github
            if "CHANGE_ME" in (g.owner + g.repo + g.path):
                self._log(f"[{core.code}] github source not configured; skipping\n")
                continue
            parent = g.path.rsplit("/", 1)[0] if "/" in g.path else ""
            root_key = (g.owner, g.repo, g.branch, parent)
            if parent and root_key not in seen_roots:
                seen_roots.add(root_key)
                self._log(f"\n[{g.owner}/{g.repo}@{g.branch}] {parent}/\n")
                try:
                    for entry in gh.list_dir(g.owner, g.repo, parent, g.branch):
                        marker = "/" if entry.type == "dir" else ""
                        self._log(f"  {entry.name}{marker}\n")
                except Exception as exc:  # noqa: BLE001
                    self._log(f"  ERROR listing {parent}: {exc}\n")

            self._log(f"\n[{core.code}] {g.path}/\n")
            try:
                entries = gh.list_dir(g.owner, g.repo, g.path, g.branch)
            except Exception as exc:  # noqa: BLE001
                self._log(f"  ERROR: {exc}\n")
                continue
            for entry in entries:
                marker = "/" if entry.type == "dir" else ""
                self._log(f"  {entry.name}{marker}\n")
                if entry.type == "dir":
                    try:
                        sub = gh.list_dir(g.owner, g.repo, entry.path, g.branch)
                    except Exception as exc:  # noqa: BLE001
                        self._log(f"    ERROR: {exc}\n")
                        continue
                    for s in sub:
                        sm = "/" if s.type == "dir" else ""
                        self._log(f"    {s.name}{sm}\n")

        self._log("=== Discovery done ===\n")
        self.after(0, self._finish_run)

    # ---- Thread-safe logging --------------------------------------------
    def _log(self, msg: str) -> None:
        self._log_queue.put(msg)

    def _add_row(self, *values: object) -> None:
        self.after(0, lambda: self.tree.insert("", "end", values=values))

    # ---- Hierarchical results rendering ---------------------------------
    def _display_report(self, report: CoreReport, out_path: str) -> None:
        """Insert one core's report as an expandable Core -> Domain -> YAML tree."""
        core_tag = self._status_tag(report.missing, report.partial)
        core_label = (
            f"{report.core_code}  ({report.core_name})   "
            f"covered {report.covered} / partial {report.partial} / "
            f"missing {report.missing} / yaml {report.total_yaml}"
        )
        core_id = self.tree.insert(
            "",
            "end",
            text=core_label,
            open=False,
            values=(
                report.total_yaml,
                report.covered,
                report.partial,
                report.missing,
                f"report: {out_path}",
            ),
            tags=("core", core_tag),
        )
        self._item_report[core_id] = out_path

        for d in report.domains:
            d_tag = self._status_tag(d.missing, d.partial)
            d_label = f"{d.github_domain}"
            d_id = self.tree.insert(
                core_id,
                "end",
                text=d_label,
                open=False,
                values=(d.total_yaml, d.covered, d.partial, d.missing, ""),
                tags=("domain", d_tag),
            )
            self._item_report[d_id] = out_path

            missing = sorted(
                (r for r in d.results if r.tier is MatchTier.NONE),
                key=lambda r: r.spec.filename,
            )
            partial = sorted(
                (r for r in d.results if r.tier is MatchTier.PARTIAL),
                key=lambda r: r.spec.filename,
            )
            for r in missing:
                self._insert_leaf(d_id, r, out_path, kind="missing")
            for r in partial:
                self._insert_leaf(d_id, r, out_path, kind="partial")

        # Auto-open the core node if it has anything to see.
        if report.missing or report.partial:
            self.tree.item(core_id, open=True)

    def _display_failure(self, core_code: str, msg: str) -> None:
        self.tree.insert(
            "",
            "end",
            text=f"{core_code}  FAILED",
            values=("-", "-", "-", "-", msg),
            tags=("core", "missing"),
        )

    def _insert_leaf(
        self,
        parent_id: str,
        r: MatchResult,
        out_path: str,
        kind: str,  # "missing" or "partial"
    ) -> None:
        if kind == "missing":
            top = r.suggestions[0][0].full_path if r.suggestions else "(no suggestion)"
            top_score = r.suggestions[0][1] if r.suggestions else 0
            detail = f"spec: {r.spec.display}   |   closest: {top} (score {top_score})"
        else:  # partial
            missing_types = [
                sm.spec.type for sm in r.sub_matches if not sub_is_type_covered(sm)
            ]
            covered_types = [
                sm.spec.type for sm in r.sub_matches if sub_is_type_covered(sm)
            ]
            detail = (
                f"spec: {r.spec.display}   |   missing types: {missing_types}   "
                f"|   covered types: {covered_types}"
            )
        label = ("[MISS] " if kind == "missing" else "[PART] ") + r.spec.filename
        item_id = self.tree.insert(
            parent_id,
            "end",
            text=label,
            values=("", "", "", "", detail),
            tags=(kind,),
        )
        self._item_report[item_id] = out_path

    def _status_tag(self, missing: int, partial: int) -> str:
        if missing:
            return "missing"
        if partial:
            return "partial"
        return "covered"

    # ---- Tree controls ---------------------------------------------------
    def _expand_issues(self) -> None:
        """Open every core/domain node that has missing or partial children."""
        for core_id in self.tree.get_children(""):
            has_issues = False
            for d_id in self.tree.get_children(core_id):
                leaves = self.tree.get_children(d_id)
                if leaves:
                    self.tree.item(d_id, open=True)
                    has_issues = True
                else:
                    self.tree.item(d_id, open=False)
            self.tree.item(core_id, open=has_issues)

    def _collapse_all(self) -> None:
        for core_id in self.tree.get_children(""):
            for d_id in self.tree.get_children(core_id):
                self.tree.item(d_id, open=False)
            self.tree.item(core_id, open=False)

    def _open_selected_report(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Pick a row first.")
            return
        path = self._item_report.get(sel[0])
        if not path:
            messagebox.showinfo("No report", "No report file associated with this row.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open failed", str(exc))

    # ---- Filter ---------------------------------------------------------
    def _apply_filter(self) -> None:
        """Detach items whose label (or descendants) don't contain the query."""
        query = self.filter_var.get().strip().lower()

        # Restore any previously detached children so we start from full tree.
        for parent, kids in list(self._all_children.items()):
            for iid, index in kids:
                try:
                    self.tree.reattach(iid, parent, index)
                except tk.TclError:
                    pass
        self._all_children.clear()

        if not query:
            return

        def matches(iid: str) -> bool:
            text = (self.tree.item(iid, "text") or "").lower()
            values = " ".join(str(v) for v in self.tree.item(iid, "values"))
            if query in text or query in values.lower():
                return True
            for child in self.tree.get_children(iid):
                if matches(child):
                    return True
            return False

        def prune(parent: str) -> None:
            kept: list[tuple[str, int]] = []
            for index, child in enumerate(self.tree.get_children(parent)):
                if matches(child):
                    prune(child)
                else:
                    kept.append((child, index))
            for iid, _ in kept:
                self.tree.detach(iid)
            if kept:
                self._all_children[parent] = kept

        prune("")
        # Expand everything that survived so matches are visible.
        for core_id in self.tree.get_children(""):
            self.tree.item(core_id, open=True)
            for d_id in self.tree.get_children(core_id):
                self.tree.item(d_id, open=True)

    def _poll_log_queue(self) -> None:
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _append_log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg)
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> int:
    app = CoverageApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
