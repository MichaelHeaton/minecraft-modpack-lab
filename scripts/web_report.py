#!/usr/bin/env python3
"""Generate a static HTML playability report from recipe dumps + pack profiles.

  python3 scripts/web_report.py --all                 # hub + every dumped pack
  python3 scripts/web_report.py --pack verdant        # one pack + refresh hub
  python3 scripts/web_report.py --compare verdant liminal

Site root: out/web/
  index.html              — hub (all packs with dumps)
  packs/<id>/…            — per-pack report
  compare/<a>-vs-<b>/…    — pack compare

Python stdlib only. Templates + assets live in web/; copies assets into out/web/.
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from profile import (  # noqa: E402
    NETHER_HINTS,
    format_world,
    load_profile,
    world_warnings,
)
from series_reach import World, targets_from  # noqa: E402

WEB_SRC = ROOT / "web"
ASSETS_SRC = WEB_SRC / "assets"
TEMPLATE = (WEB_SRC / "templates" / "page.html").read_text(encoding="utf-8")
HUB_ROOT = ROOT / "out" / "web"
SKIP_OUT_DIRS = frozenset({"web", "compare"})


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def copy_assets(dest: Path) -> None:
    assets = dest / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    shutil.copytree(ASSETS_SRC, assets)


def discover_dumped_packs() -> list[str]:
    """Pack ids under out/ that have recipe_data.json."""
    out = ROOT / "out"
    if not out.is_dir():
        return []
    ids: list[str] = []
    for p in sorted(out.iterdir()):
        if not p.is_dir() or p.name.startswith(".") or p.name in SKIP_OUT_DIRS:
            continue
        if (p / "recipe_data.json").is_file():
            ids.append(p.name)
    return ids


def pack_label(pack_id: str) -> str:
    try:
        return str(load_profile(pack_id).get("label") or pack_id)
    except Exception:
        return pack_id


def pack_switcher_html(
    *,
    current: str | None,
    packs: list[str],
    page: str = "index.html",
    from_hub: bool = False,
    from_compare: bool = False,
) -> str:
    """Dropdown to jump between hub and pack reports."""
    if from_hub:
        hub_href = "index.html"
        pack_href = lambda pid: f"packs/{pid}/{page}"  # noqa: E731
    elif from_compare:
        hub_href = "../../index.html"
        pack_href = lambda pid: f"../../packs/{pid}/{page}"  # noqa: E731
    else:
        hub_href = "../../index.html"
        pack_href = lambda pid: f"../{pid}/{page}"  # noqa: E731

    opts = [
        f'<option value="{esc(hub_href)}"'
        f'{" selected" if current is None else ""}>All packs</option>'
    ]
    for pid in packs:
        sel = " selected" if pid == current else ""
        opts.append(
            f'<option value="{esc(pack_href(pid))}"{sel}>'
            f"{esc(pid)} — {esc(pack_label(pid))}</option>"
        )
    return (
        '      <label class="pack-switch">'
        "<span>Pack</span>"
        '<select data-pack-switch aria-label="Switch pack">'
        + "".join(opts)
        + "</select></label>"
    )


def render_page(
    *,
    title: str,
    nav: str,
    body: str,
    out: Path,
    assets_rel: str = "assets",
    home: str = "index.html",
    pack_switcher: str = "",
) -> None:
    text = (
        TEMPLATE.replace("{{TITLE}}", esc(title))
        .replace("{{ASSETS}}", assets_rel)
        .replace("{{HOME}}", home)
        .replace("{{PACK_SWITCHER}}", pack_switcher)
        .replace("{{NAV}}", nav)
        .replace("{{BODY}}", body)
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def nav_links(active: str, pages: list[tuple[str, str]]) -> str:
    bits = []
    for href, label in pages:
        cls = ' class="active"' if href == active else ""
        bits.append(f'      <a href="{esc(href)}"{cls}>{esc(label)}</a>')
    return "\n".join(bits)


def load_insights(pack_out: Path) -> dict[str, object]:
    """Load optional sibling-agent insights; omit keys whose files are missing."""
    insights_dir = pack_out / "insights"
    found: dict[str, object] = {}
    if not insights_dir.is_dir():
        return found
    for name in ("economics.json", "progression.json"):
        path = insights_dir / name
        if path.is_file():
            try:
                found[name.replace(".json", "")] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
    return found


def chicken_egg_signals(w: World) -> list[str]:
    signals: list[str] = []
    if "minecraft:blaze_powder" in w.items and "minecraft:blaze_rod" not in w.items:
        signals.append("blaze_powder reachable but blaze_rod is not — compacting/casting gap")
    if "minecraft:netherite_scrap" in w.items and "minecraft:netherite_ingot" not in w.items:
        signals.append("netherite_scrap reachable but netherite_ingot is not")
    for metal, label in (
        ("silentgear:crimson_iron_ingot", "crimson iron"),
        ("silentgear:azure_silver_ingot", "azure silver"),
        ("silentgear:tyrian_steel_ingot", "tyrian steel"),
    ):
        if metal in w.known and metal not in w.items:
            signals.append(f"{label} known in dump but no route from this start")
    return signals


def pack_recipes(dump: dict) -> list[tuple[str, list[dict]]]:
    out: list[tuple[str, list[dict]]] = []
    for item, bucket in (dump.get("recipes") or {}).items():
        routes = [e for e in (bucket.get("mod") or []) if e.get("origin") == "pack"]
        if routes:
            out.append((item, routes))
    out.sort(key=lambda x: x[0])
    return out


def analyze_pack(pack_id: str) -> dict:
    profile = load_profile(pack_id)
    dump_path = ROOT / "out" / pack_id / "recipe_data.json"
    if not dump_path.is_file():
        raise FileNotFoundError(f"no dump at {dump_path}; run: make dump PACK={pack_id} EULA=1")

    dump = json.loads(dump_path.read_text(encoding="utf-8"))
    start = json.loads(Path(profile["start"]).read_text(encoding="utf-8"))
    targets = targets_from(profile["targets"])
    w = World(dump, start)
    passes = w.close()

    ok_list: list[dict] = []
    bad_list: list[dict] = []
    world = profile["world"]
    for t in targets:
        row = {
            "id": t["id"],
            "why": t.get("why", ""),
            "ok": t["id"] in w.items,
            "depth": w.items.get(t["id"]),
            "known": t["id"] in w.known,
            "chain": [],
            "hint": "",
            "routes": ((dump.get("recipes") or {}).get(t["id"]) or {}).get("mod") or [],
        }
        if row["ok"]:
            row["chain"] = w.chain(t["id"])
            ok_list.append(row)
        else:
            if t["id"] in NETHER_HINTS and not world.get("nether"):
                row["hint"] = "nether=false — need overworld substitute"
            if world.get("ore_veins") is False and "_ore" in t["id"]:
                row["hint"] = "ore_veins=false"
            bad_list.append(row)

    insights = load_insights(ROOT / "out" / pack_id)
    return {
        "pack_id": pack_id,
        "profile": profile,
        "dump": dump,
        "dump_path": dump_path,
        "start": start,
        "world": w,
        "passes": passes,
        "targets_ok": ok_list,
        "targets_bad": bad_list,
        "targets_all": ok_list + bad_list,
        "signals": chicken_egg_signals(w),
        "warnings": world_warnings(profile, start),
        "pack_items": pack_recipes(dump),
        "insights": insights,
        "verdict_ok": len(bad_list) == 0,
    }


def flag_html(world: dict) -> str:
    defs = [
        ("spawn", world.get("spawn"), None),
        ("terrain", world.get("terrain"), None),
        ("ore veins", "yes" if world.get("ore_veins") else "no", world.get("ore_veins")),
        ("nether", "yes" if world.get("nether") else "no", world.get("nether")),
        ("end", "yes" if world.get("end") else "no", world.get("end")),
        ("villages", "yes" if world.get("villages") else "no", world.get("villages")),
    ]
    cells = []
    for label, value, on_off in defs:
        cls = ""
        if on_off is True:
            cls = " on"
        elif on_off is False:
            cls = " off"
        cells.append(
            f'<div class="flag"><span class="label">{esc(label)}</span>'
            f'<span class="value{cls}">{esc(value)}</span></div>'
        )
    return '<div class="flags">' + "".join(cells) + "</div>"


def chain_html(lines: list[str]) -> str:
    if not lines:
        return ""
    rendered = []
    for line in lines:
        safe = esc(line)
        if "(start)" in line:
            safe = safe.replace("(start)", '<span class="start-mark">(start)</span>')
        # highlight the leading item id before "  <-" or "  (start)"
        if "  &lt;-" in safe or "  (" in safe:
            # already escaped; split on first double-space after indent is hard — keep plain
            pass
        rendered.append(safe)
    return '<pre class="chain">' + "\n".join(rendered) + "</pre>"


def insights_economics_html(data: dict) -> str:
    parts = ['<section id="insights-economics"><h2>Economics</h2>']
    if data.get("verified") is False:
        parts.append(
            '<p class="section-note">Jar/config scrape — <span class="badge">unverified</span> '
            "(heuristics; not RF-validated).</p>"
        )
    stats = data.get("stats") or {}
    if stats:
        kinds = stats.get("generator_kinds") or {}
        kind_bits = ", ".join(f"{k}={v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])[:8])
        parts.append('<div class="flags">')
        for label, key in (
            ("jars", "jars_scanned"),
            ("generators", "generators_found"),
            ("clusters", "redundant_generator_clusters"),
            ("tier groups", "tier_groups"),
            ("config hits", "config_hits"),
        ):
            if key in stats:
                parts.append(
                    f'<div class="flag"><span class="label">{esc(label)}</span>'
                    f'<span class="value">{esc(stats[key])}</span></div>'
                )
        parts.append("</div>")
        if kind_bits:
            parts.append(f'<p class="section-note">Generator kinds: {esc(kind_bits)}</p>')

    clusters = data.get("redundant_generator_clusters") or []
    if clusters:
        parts.append("<h3>Redundant generator clusters</h3>")
        parts.append(
            '<div class="table-wrap"><table class="data"><thead>'
            "<tr><th>Kind</th><th>Size</th><th>Namespaces</th><th>Families</th><th>Reason</th></tr>"
            "</thead><tbody>"
        )
        for c in clusters[:20]:
            parts.append(
                "<tr>"
                f'<td class="mono">{esc(c.get("kind"))}</td>'
                f'<td class="depth">{esc(c.get("size"))}</td>'
                f'<td class="mono">{esc(", ".join(c.get("namespaces") or []))}</td>'
                f'<td class="mono">{esc(", ".join(c.get("families") or [])[:6])}</td>'
                f'<td class="why">{esc(c.get("reason"))}</td>'
                "</tr>"
            )
        parts.append("</tbody></table></div>")

    tiers = data.get("machine_tier_groups") or []
    if tiers:
        parts.append("<h3>Machine tier groups</h3>")
        parts.append(
            '<p class="section-note">Naming heuristics — side-grades may be mislabeled.</p>'
            '<div class="table-wrap"><table class="data"><thead>'
            "<tr><th>Namespace</th><th>Family</th><th>Tiers</th><th>Count</th></tr>"
            "</thead><tbody>"
        )
        for g in tiers[:24]:
            parts.append(
                "<tr>"
                f'<td class="mono">{esc(g.get("namespace"))}</td>'
                f'<td class="mono">{esc(g.get("family"))}</td>'
                f'<td class="mono">{esc(", ".join(g.get("tiers") or []))}</td>'
                f'<td class="depth">{esc(g.get("tier_count"))}</td>'
                "</tr>"
            )
        parts.append("</tbody></table></div>")
        if len(tiers) > 24:
            parts.append(f'<p class="empty">… {len(tiers) - 24} more groups</p>')

    cfg = data.get("config_disabled_or_blacklist") or []
    if cfg:
        parts.append(
            f"<h3>Config disabled / blacklist hits</h3>"
            f'<p class="section-note">{esc(len(cfg))} regex hits (may include empty lists).</p>'
        )
    parts.append("</section>")
    return "\n".join(parts)


def insights_progression_html(data: dict) -> str:
    parts = ['<section id="insights-progression"><h2>Progression</h2>']
    parts.append(
        f'<p class="section-note">'
        f'{esc(data.get("chapter_count", "—"))} chapters · '
        f'targets {esc(data.get("targets_ok"))} OK / {esc(data.get("targets_blocked"))} blocked'
        f"</p>"
    )

    blocked = data.get("blocked_targets") or []
    if blocked:
        parts.append("<h3>Blocked targets</h3>")
        parts.append(
            '<div class="table-wrap"><table class="data"><thead>'
            "<tr><th>Item</th><th>Why</th><th>Note</th></tr></thead><tbody>"
        )
        for t in blocked:
            parts.append(
                f'<tr class="fail-row">'
                f'<td class="item">{esc(t.get("id"))}</td>'
                f'<td class="why">{esc(t.get("why"))}</td>'
                f'<td class="why">{esc(t.get("note"))}</td>'
                f"</tr>"
            )
        parts.append("</tbody></table></div>")

    order = data.get("suggested_quest_order") or []
    if order:
        parts.append("<h3>Suggested quest order</h3>")
        parts.append(
            '<p class="section-note">Mods ranked by median target depth (draft chapters).</p>'
            '<div class="table-wrap"><table class="data"><thead>'
            "<tr><th>Rank</th><th>Mod</th><th>Median target depth</th>"
            "<th>Targets</th><th>Items</th></tr></thead><tbody>"
        )
        for row in order[:30]:
            parts.append(
                "<tr>"
                f'<td class="depth">{esc(row.get("rank"))}</td>'
                f'<td class="mono">{esc(row.get("mod"))}</td>'
                f'<td class="depth">{esc(row.get("median_target_depth"))}</td>'
                f'<td class="depth">{esc(row.get("target_count"))}</td>'
                f'<td class="depth">{esc(row.get("item_count"))}</td>'
                "</tr>"
            )
        parts.append("</tbody></table></div>")
        if len(order) > 30:
            parts.append(f'<p class="empty">… {len(order) - 30} more mods</p>')
    parts.append("</section>")
    return "\n".join(parts)


def insights_section(insights: dict[str, object]) -> str:
    if not insights:
        return ""
    parts = []
    if "economics" in insights and isinstance(insights["economics"], dict):
        parts.append(insights_economics_html(insights["economics"]))
    if "progression" in insights and isinstance(insights["progression"], dict):
        parts.append(insights_progression_html(insights["progression"]))
    # Any other insight files: compact key table (no empty placeholder if none)
    for key, data in insights.items():
        if key in ("economics", "progression"):
            continue
        if not isinstance(data, dict):
            continue
        parts.append(f'<section id="insights-{esc(key)}"><h2>{esc(key)}</h2>')
        summary = data.get("summary") or data.get("note") or data.get("description")
        if summary:
            parts.append(f'<p class="section-note">{esc(summary)}</p>')
        rows = []
        for k, v in data.items():
            if k in ("summary", "note", "description"):
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                rows.append(f'<tr><td class="mono">{esc(k)}</td><td>{esc(v)}</td></tr>')
            elif isinstance(v, list):
                rows.append(
                    f'<tr><td class="mono">{esc(k)}</td>'
                    f'<td class="mono">{esc(len(v))} entries</td></tr>'
                )
            elif isinstance(v, dict):
                rows.append(
                    f'<tr><td class="mono">{esc(k)}</td>'
                    f'<td class="mono">{esc(len(v))} keys</td></tr>'
                )
        if rows:
            parts.append(
                '<div class="table-wrap"><table class="data"><thead>'
                "<tr><th>Key</th><th>Value</th></tr></thead><tbody>"
                + "".join(rows)
                + "</tbody></table></div>"
            )
        parts.append("</section>")
    return "\n".join(parts)


def toolbar(*, fail: bool = False, pack: bool = False, placeholder: str = "Filter…") -> str:
    bits = [
        f'<div class="toolbar">',
        f'<input type="search" data-filter-search placeholder="{esc(placeholder)}" aria-label="Filter">',
    ]
    if fail:
        bits.append('<label><input type="checkbox" data-filter-fail> FAIL only</label>')
    if pack:
        bits.append('<label><input type="checkbox" data-filter-pack> pack origin</label>')
    bits.append("</div>")
    return "".join(bits)


def write_pack_site(pack_id: str, *, all_packs: list[str] | None = None) -> Path:
    data = analyze_pack(pack_id)
    profile = data["profile"]
    dump = data["dump"]
    label = profile.get("label") or pack_id
    packs = all_packs if all_packs is not None else discover_dumped_packs()
    if pack_id not in packs:
        packs = sorted(set(packs) | {pack_id})

    out_dir = HUB_ROOT / "packs" / pack_id
    out_dir.mkdir(parents=True, exist_ok=True)
    # Shared assets live on the hub root (copied by write_hub / --all)
    HUB_ROOT.mkdir(parents=True, exist_ok=True)
    if not (HUB_ROOT / "assets").is_dir():
        copy_assets(HUB_ROOT)

    pages = [
        ("index.html", "Overview"),
        ("targets.html", "Targets"),
        ("pack-recipes.html", "Pack recipes"),
        ("coverage.html", "Coverage"),
    ]
    switcher = pack_switcher_html(current=pack_id, packs=packs, page="index.html")
    home = "../../index.html"
    assets = "../../assets"

    n_ok = len(data["targets_ok"])
    n_bad = len(data["targets_bad"])
    n_tgt = n_ok + n_bad
    verdict_cls = "ok" if data["verdict_ok"] else "fail"
    verdict_text = (
        "PLAYABLE — all targets reachable"
        if data["verdict_ok"]
        else f"{n_bad} target(s) blocked"
    )

    # —— index ——
    body = f"""
    <header class="hero">
      <p class="kicker">Playability report · {esc(pack_id)}</p>
      <h1>{esc(label)}</h1>
      <p class="lede">{esc(profile.get("notes") or "")}</p>
      <div class="verdict {verdict_cls}">{esc(verdict_text)}</div>
      <dl class="meta-row">
        <span class="pair"><dt>world</dt><dd>{esc(format_world(profile["world"]))}</dd></span>
        <span class="pair"><dt>items</dt><dd>{esc(dump.get("item_count"))}</dd></span>
        <span class="pair"><dt>reachable</dt><dd>{esc(len(data["world"].items))} after {esc(data["passes"])} passes</dd></span>
        <span class="pair"><dt>targets</dt><dd>{esc(n_ok)}/{esc(n_tgt)} OK</dd></span>
        <span class="pair"><dt>source</dt><dd>{esc(dump.get("source"))}</dd></span>
      </dl>
    </header>

    <section>
      <h2>World flags</h2>
      <p class="section-note">Profile assumptions used for this reachability run.</p>
      {flag_html(profile["world"])}
    </section>
"""
    if data["warnings"]:
        body += '<section><h2>Profile warnings</h2><ul class="signal-list">'
        for wmsg in data["warnings"]:
            body += f"<li>{esc(wmsg)}</li>"
        body += "</ul></section>"

    body += f"""
    <section>
      <h2>Targets</h2>
      <p class="section-note">
        {esc(n_ok)} reachable, {esc(n_bad)} blocked.
        <a href="targets.html">Open detail + craft paths</a>
      </p>
      {toolbar(fail=True, placeholder="Filter targets…")}
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr><th>Status</th><th>Item</th><th>Depth</th><th>Why</th></tr>
          </thead>
          <tbody>
"""
    for row in data["targets_all"]:
        status = "ok" if row["ok"] else "fail"
        status_label = "OK" if row["ok"] else "FAIL"
        depth = str(row["depth"]) if row["ok"] else "—"
        filt = f"{row['id']} {row['why']} {status_label}".lower()
        body += (
            f'<tr class="{status}-row" data-filter-row data-status="{status}" '
            f'data-filter-text="{esc(filt)}">'
            f'<td class="status">{status_label}</td>'
            f'<td class="item"><a class="item-link" href="targets.html#{esc(row["id"])}">{esc(row["id"])}</a></td>'
            f'<td class="depth">{esc(depth)}</td>'
            f'<td class="why">{esc(row["why"])}</td>'
            f"</tr>\n"
        )
    body += """
          </tbody>
        </table>
      </div>
    </section>
"""

    body += '<section><h2>Chicken-and-egg signals</h2>'
    if data["signals"]:
        body += '<ul class="signal-list">'
        for s in data["signals"]:
            body += f"<li>{esc(s)}</li>"
        body += "</ul>"
    else:
        body += '<p class="empty">None detected from simple heuristics.</p>'
    body += "</section>"

    body += insights_section(data["insights"])

    n_pack = len(data["pack_items"])
    body += f"""
    <section>
      <h2>Pack-authored recipes</h2>
      <p class="section-note">
        {esc(n_pack)} item(s) with <span class="badge pack">pack</span> origin
        (namespaces: {esc(", ".join(dump.get("pack_namespaces") or []) or "—")}).
        <a href="pack-recipes.html">Full list</a>
      </p>
    </section>
"""

    render_page(
        title=f"{label} — playability",
        nav=nav_links("index.html", pages),
        body=body,
        out=out_dir / "index.html",
        assets_rel=assets,
        home=home,
        pack_switcher=switcher,
    )

    # —— targets ——
    tbody = f"""
    <header class="hero">
      <p class="kicker">{esc(label)}</p>
      <h1>Targets</h1>
      <p class="lede">Each design target with cheapest craft path when reachable.</p>
    </header>
    {toolbar(fail=True, placeholder="Filter targets…")}
"""
    for row in data["targets_all"]:
        status = "ok" if row["ok"] else "fail"
        filt = f"{row['id']} {row['why']}".lower()
        depth_bit = (
            f'<span class="depth-num">depth {esc(row["depth"])}</span>'
            if row["ok"]
            else '<span class="badge fail">FAIL</span>'
        )
        tbody += (
            f'<article class="target {status}" id="{esc(row["id"])}" '
            f'data-filter-row data-status="{status}" data-filter-text="{esc(filt)}">'
            f'<div class="target-head">'
            f'<span class="id">{esc(row["id"])}</span>'
            f'<span class="badge {status}">{"OK" if row["ok"] else "FAIL"}</span>'
            f"{depth_bit}"
            f"</div>"
            f'<p class="why">{esc(row["why"])}</p>'
        )
        if row["ok"]:
            tbody += chain_html(row["chain"])
        else:
            known = "known in dump" if row["known"] else "NOT IN DUMP"
            tbody += f'<p class="why">{esc(known)}'
            if row["hint"]:
                tbody += f' · {esc(row["hint"])}'
            tbody += "</p>"
            if row["routes"]:
                tbody += '<ul class="blocked-list">'
                for e in row["routes"][:8]:
                    origin = e.get("origin") or "?"
                    badge = "pack" if origin == "pack" else "mod"
                    tbody += (
                        f'<li><span class="badge {badge}">{esc(origin)}</span> '
                        f'{esc(e.get("type"))} · {esc(e.get("id"))}</li>'
                    )
                tbody += "</ul>"
            else:
                tbody += '<p class="empty">No recipes for this item in the dump.</p>'
        tbody += "</article>\n"

    render_page(
        title=f"{label} — targets",
        nav=nav_links("targets.html", pages),
        body=tbody,
        out=out_dir / "targets.html",
        assets_rel=assets,
        home=home,
        pack_switcher=pack_switcher_html(current=pack_id, packs=packs, page="targets.html"),
    )

    # —— pack recipes ——
    pbody = f"""
    <header class="hero">
      <p class="kicker">{esc(label)}</p>
      <h1>Pack-authored recipes</h1>
      <p class="lede">
        Routes tagged <span class="badge pack">pack</span>
        (KubeJS / pack datapack namespaces). Origins dump:
        {esc(dump.get("origins"))}.
      </p>
    </header>
    {toolbar(placeholder="Filter recipes…")}
"""
    if not data["pack_items"]:
        pbody += '<p class="empty">None — all routes came from mod jars.</p>'
    else:
        pbody += """
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>Item</th><th>Recipe</th><th>Type</th><th>Ingredients</th></tr></thead>
          <tbody>
"""
        for item, routes in data["pack_items"]:
            for e in routes:
                ings = e.get("ings") or []
                ing_txt = ", ".join(
                    f'{i.get("value")}×{i.get("count", 1)}' for i in ings[:8]
                )
                if len(ings) > 8:
                    ing_txt += "…"
                filt = f"{item} {e.get('id')} {e.get('type')}".lower()
                pbody += (
                    f'<tr class="recipe-row" data-filter-row data-origin="pack" '
                    f'data-filter-text="{esc(filt)}">'
                    f'<td class="item">{esc(item)}</td>'
                    f'<td class="mono">{esc(e.get("id"))}</td>'
                    f'<td class="mono">{esc(e.get("type"))}</td>'
                    f'<td class="mono">{esc(ing_txt)}</td>'
                    f"</tr>\n"
                )
        pbody += "</tbody></table></div>"

    render_page(
        title=f"{label} — pack recipes",
        nav=nav_links("pack-recipes.html", pages),
        body=pbody,
        out=out_dir / "pack-recipes.html",
        assets_rel=assets,
        home=home,
        pack_switcher=pack_switcher_html(
            current=pack_id, packs=packs, page="pack-recipes.html"
        ),
    )

    # —— coverage ——
    skipped = dump.get("skipped_types") or {}
    non_route = dump.get("non_route_types") or {}
    unparsed = dump.get("unparsed") or 0
    loot = dump.get("loot") or {}
    cbody = f"""
    <header class="hero">
      <p class="kicker">{esc(label)}</p>
      <h1>Coverage</h1>
      <p class="lede">Parsed routes vs intentionally ignored types vs remaining debt.</p>
      <dl class="meta-row">
        <span class="pair"><dt>loot keys</dt><dd>{esc(len(loot))}</dd></span>
        <span class="pair"><dt>unparsed count</dt><dd>{esc(unparsed)}</dd></span>
        <span class="pair"><dt>skipped types</dt><dd>{esc(len(skipped))}</dd></span>
        <span class="pair"><dt>non-route types</dt><dd>{esc(len(non_route))}</dd></span>
      </dl>
    </header>
"""
    cbody += '<section><h2>Unparsed / skipped recipe types</h2>'
    if skipped:
        cbody += (
            '<p class="section-note">Coverage debt — may hide real craft routes.</p>'
            '<div class="table-wrap"><table class="data"><thead>'
            "<tr><th>Count</th><th>Type</th></tr></thead><tbody>"
        )
        for rtype, n in sorted(skipped.items(), key=lambda kv: -kv[1]):
            cbody += f'<tr><td class="depth">{esc(n)}</td><td class="mono">{esc(rtype)}</td></tr>\n'
        cbody += "</tbody></table></div>"
    else:
        cbody += (
            '<p class="empty">None — every snapshot recipe was parsed or classified non-route.</p>'
        )
    cbody += "</section>"

    cbody += '<section><h2>Non-route types</h2>'
    if non_route:
        cbody += (
            '<p class="section-note">Intentionally ignored — no item craft path.</p>'
            '<div class="table-wrap"><table class="data"><thead>'
            "<tr><th>Count</th><th>Type</th></tr></thead><tbody>"
        )
        for rtype, n in sorted(non_route.items(), key=lambda kv: -kv[1]):
            cbody += f'<tr><td class="depth">{esc(n)}</td><td class="mono">{esc(rtype)}</td></tr>\n'
        cbody += "</tbody></table></div>"
    else:
        cbody += '<p class="empty">None recorded.</p>'
    cbody += "</section>"

    ents = sum(1 for k in loot if k.startswith("entities/"))
    chests = sum(1 for k in loot if k.startswith("chests/"))
    blocks = sum(1 for k in loot if k.startswith("blocks/"))
    cbody += f"""
    <section>
      <h2>Loot / GLM</h2>
      <div class="flags">
        <div class="flag"><span class="label">entities</span><span class="value">{esc(ents)}</span></div>
        <div class="flag"><span class="label">chests</span><span class="value">{esc(chests)}</span></div>
        <div class="flag"><span class="label">blocks</span><span class="value">{esc(blocks)}</span></div>
        <div class="flag"><span class="label">total keys</span><span class="value">{esc(len(loot))}</span></div>
      </div>
    </section>
"""
    render_page(
        title=f"{label} — coverage",
        nav=nav_links("coverage.html", pages),
        body=cbody,
        out=out_dir / "coverage.html",
        assets_rel=assets,
        home=home,
        pack_switcher=pack_switcher_html(
            current=pack_id, packs=packs, page="coverage.html"
        ),
    )

    # Legacy redirect for old out/<pack>/web/ bookmarks
    legacy = ROOT / "out" / pack_id / "web"
    legacy.mkdir(parents=True, exist_ok=True)
    rel = f"../../web/packs/{pack_id}/index.html"
    (legacy / "index.html").write_text(
        "<!DOCTYPE html><meta charset=utf-8>"
        f'<meta http-equiv="refresh" content="0;url={esc(rel)}">'
        f'<p>Moved to <a href="{esc(rel)}">{esc(rel)}</a>.</p>\n',
        encoding="utf-8",
    )

    print(f"wrote {out_dir}/")
    return out_dir


def write_hub(packs: list[str] | None = None) -> Path:
    """Hub landing page listing every dumped pack + reference wishlist."""
    packs = packs if packs is not None else discover_dumped_packs()
    HUB_ROOT.mkdir(parents=True, exist_ok=True)
    copy_assets(HUB_ROOT)

    try:
        from packs import load_packs, load_references  # noqa: WPS433

        registry = load_packs()
        refs = load_references()
    except Exception:
        registry, refs = {}, {}

    def role_of(pid: str) -> str:
        return (registry.get(pid) or {}).get("role") or "build"

    def card_for(pid: str) -> str | None:
        try:
            data = analyze_pack(pid)
        except FileNotFoundError:
            return None
        label = data["profile"].get("label") or pid
        n_ok = len(data["targets_ok"])
        n_bad = len(data["targets_bad"])
        n_tgt = n_ok + n_bad
        vcls = "ok" if data["verdict_ok"] else "fail"
        vtxt = "PLAYABLE" if data["verdict_ok"] else f"{n_bad} blocked"
        role = role_of(pid)
        return (
            f'<a class="pack-card" href="packs/{esc(pid)}/index.html">'
            f"<h3>{esc(label)}</h3>"
            f'<div class="pack-id">{esc(pid)} · {esc(role)}</div>'
            f'<div class="verdict {vcls}">{esc(vtxt)}</div>'
            f'<p class="meta">{esc(n_ok)}/{esc(n_tgt)} targets · '
            f'{esc(data["dump"].get("item_count"))} items · '
            f'{esc(len(data["pack_items"]))} pack recipes</p>'
            f"</a>"
        )

    build_cards = []
    ref_cards = []
    for pid in packs:
        html_card = card_for(pid)
        if not html_card:
            continue
        if role_of(pid) == "reference":
            ref_cards.append(html_card)
        else:
            build_cards.append(html_card)

    wishlist = []
    for rid, e in sorted(refs.items()):
        if e.get("status") in ("local", "dumped") and rid in packs:
            continue
        cf = e.get("curseforge") or "#"
        notes = e.get("notes") or "Reference pack — download, then make add --role reference"
        wishlist.append(
            f'<a class="pack-card" href="{esc(cf)}" target="_blank" rel="noopener">'
            f"<h3>{esc(e.get('label') or rid)}</h3>"
            f'<div class="pack-id">{esc(rid)} · wishlist</div>'
            f'<p class="meta">{esc(notes)}</p>'
            f"</a>"
        )

    compare_links = []
    if len(packs) >= 2:
        for i, a in enumerate(packs):
            for b in packs[i + 1 :]:
                compare_links.append(
                    f'<li><a href="compare/{esc(a)}-vs-{esc(b)}/index.html">'
                    f"{esc(a)} vs {esc(b)}</a></li>"
                )

    corpus_note = ""
    corpus_md = ROOT / "out" / "corpus" / "mods.md"
    if corpus_md.is_file():
        corpus_note = (
            '<p class="section-note"><a href="corpus.html">Mod corpus</a> — '
            "which mods are core vs unique across builds + references.</p>"
        )

    body = f"""
    <header class="hero">
      <p class="kicker">modpack-lab</p>
      <h1>Packs</h1>
      <p class="lede">
        Builds you are authoring, plus reference packs for ideas and baselines.
        Switch packs from the nav. Re-run <code>make web</code> after dumps.
      </p>
      <dl class="meta-row">
        <span class="pair"><dt>dumps</dt><dd>{esc(len(packs))}</dd></span>
        <span class="pair"><dt>wishlist</dt><dd>{esc(len(wishlist))}</dd></span>
      </dl>
    </header>
    {corpus_note}
"""
    body += "<section><h2>Builds</h2>"
    if build_cards:
        body += f'<div class="pack-card-grid">{"".join(build_cards)}</div>'
    else:
        body += (
            '<p class="empty">No build dumps yet. '
            "<code>make add DIR=…</code> then <code>make dump PACK=… EULA=1</code>.</p>"
        )
    body += "</section>"

    body += "<section><h2>References (dumped)</h2>"
    if ref_cards:
        body += f'<div class="pack-card-grid">{"".join(ref_cards)}</div>'
    else:
        body += (
            '<p class="empty">No local reference dumps yet. '
            "Download a wishlist pack, then "
            "<code>make add DIR=… --role reference --id atm10</code>.</p>"
        )
    body += "</section>"

    if wishlist:
        body += (
            "<section><h2>Reference wishlist</h2>"
            '<p class="section-note">CurseForge links — not on disk yet '
            "(see <code>packs.references.toml</code> / <code>make refs</code>).</p>"
            f'<div class="pack-card-grid">{"".join(wishlist)}</div></section>'
        )

    if compare_links:
        body += (
            "<section><h2>Compares</h2>"
            '<p class="section-note">Pairwise reachability + pack-recipe diffs.</p>'
            f"<ul class=\"signal-list\">{''.join(compare_links)}</ul></section>"
        )

    # Optional corpus page (copy markdown-ish summary into HTML if present)
    if corpus_md.is_file():
        try:
            from mod_corpus import build_corpus  # noqa: WPS433

            cdata = build_corpus()
            cbody = (
                '<header class="hero"><p class="kicker">Corpus</p>'
                "<h1>Mod frequency</h1>"
                f'<p class="lede">{esc(cdata["pack_count"])} packs · '
                f'{esc(cdata["unique_mods"])} unique mods. '
                "Core = in most packs; unique = only one.</p></header>"
                "<section><h2>Core (non-platform)</h2><ul class=\"signal-list\">"
            )
            for m in cdata["mods"]:
                if m["band"] != "core" or m["platformish"]:
                    continue
                cbody += (
                    f"<li><code>{esc(m['mod'])}</code> — "
                    f"{esc(m['pack_count'])}/{esc(cdata['pack_count'])}</li>"
                )
            cbody += "</ul></section>"
            render_page(
                title="Mod corpus",
                nav='      <a href="index.html">Hub</a>',
                body=cbody,
                out=HUB_ROOT / "corpus.html",
                assets_rel="assets",
                home="index.html",
                pack_switcher=pack_switcher_html(
                    current=None, packs=packs, page="index.html", from_hub=True
                ),
            )
        except Exception:
            pass

    render_page(
        title="modpack-lab — packs",
        nav="",
        body=body,
        out=HUB_ROOT / "index.html",
        assets_rel="assets",
        home="index.html",
        pack_switcher=pack_switcher_html(
            current=None, packs=packs, page="index.html", from_hub=True
        ),
    )
    print(f"wrote {HUB_ROOT / 'index.html'}")
    return HUB_ROOT


def _routes(dump: dict, item: str) -> list[dict]:
    return list(((dump.get("recipes") or {}).get(item) or {}).get("mod") or [])


def load_or_build_attribute(pack_a: str, pack_b: str) -> dict | None:
    """Load out/diffs/<a>-vs-<b>/attribute.json, generating it when packs are registered."""
    path = ROOT / "out" / "diffs" / f"{pack_a}-vs-{pack_b}" / "attribute.json"
    if not path.is_file():
        try:
            from attribute_diff import attribute  # noqa: WPS433

            data = attribute(pack_a, pack_b)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            md = ROOT / "out" / "diffs" / f"{pack_a}-vs-{pack_b}" / "attribute.md"
            from attribute_diff import render_md  # noqa: WPS433

            md.write_text(render_md(data), encoding="utf-8")
            return data
        except SystemExit:
            return None
        except Exception:
            return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def attribute_section_html(attr: dict, pack_a: str, pack_b: str) -> str:
    mods = attr.get("mods") or {}
    kube = attr.get("kubejs_and_datapacks") or {}
    hints = attr.get("datapack_recipes_only_in_a") or []
    pr = attr.get("pack_origin_recipes") or {}
    parts = [
        '<section id="attribute">',
        "<h2>Source attribute</h2>",
        '<p class="section-note">'
        f"Why {esc(pack_a)} differs from {esc(pack_b)} at the packwiz / KubeJS level. "
        f'<a href="attribute.html">Full attribute page</a>'
        "</p>",
        '<div class="flags">',
        f'<div class="flag"><span class="label">mods only {esc(pack_a)}</span>'
        f'<span class="value">{esc(len(mods.get("only_a") or []))}</span></div>',
        f'<div class="flag"><span class="label">mods only {esc(pack_b)}</span>'
        f'<span class="value">{esc(len(mods.get("only_b") or []))}</span></div>',
        f'<div class="flag"><span class="label">kubejs only {esc(pack_a)}</span>'
        f'<span class="value">{esc(len(kube.get("only_a") or []))}</span></div>',
        f'<div class="flag"><span class="label">datapack recipes</span>'
        f'<span class="value">{esc(len(hints))}</span></div>',
        "</div>",
    ]
    if hints:
        parts.append(f"<h3>Datapack recipes only in {esc(pack_a)} (copy candidates)</h3>")
        parts.append("<ul class=\"signal-list\">")
        for h in hints[:12]:
            parts.append(f"<li><code>{esc(h.get('file'))}</code></li>")
        if len(hints) > 12:
            parts.append(f"<li>… +{len(hints) - 12} more on <a href=\"attribute.html\">attribute page</a></li>")
        parts.append("</ul>")
    only_recipes = pr.get("only_a") or []
    if only_recipes:
        parts.append(f"<h3>Pack-origin recipe ids only in {esc(pack_a)}</h3>")
        parts.append("<ul class=\"signal-list\">")
        for r in only_recipes[:8]:
            parts.append(
                f"<li><code>{esc(r.get('id'))}</code> → <code>{esc(r.get('item'))}</code></li>"
            )
        parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def attribute_page_html(attr: dict, pack_a: str, pack_b: str) -> str:
    mods = attr.get("mods") or {}
    kube = attr.get("kubejs_and_datapacks") or {}
    hints = attr.get("datapack_recipes_only_in_a") or []
    pr = attr.get("pack_origin_recipes") or {}
    sc = attr.get("server_config") or {}
    body = f"""
    <header class="hero">
      <p class="kicker">Source attribute</p>
      <h1>{esc(pack_a)} vs {esc(pack_b)}</h1>
      <p class="lede">
        File-level diff of packwiz mods, KubeJS/datapacks, and dump configs.
        Copy candidates are datapack recipes present only in {esc(pack_a)}.
      </p>
    </header>
    <section>
      <h2>Mods</h2>
      <p class="section-note">
        {esc(pack_a)}={esc(mods.get("count_a"))} · {esc(pack_b)}={esc(mods.get("count_b"))} ·
        shared {esc(mods.get("shared"))}
      </p>
"""
    for label, key in ((pack_a, "only_a"), (pack_b, "only_b")):
        ids = mods.get(key) or []
        body += f"<h3>Only in {esc(label)} ({esc(len(ids))})</h3>"
        if not ids:
            body += '<p class="empty">(none)</p>'
        else:
            body += (
                f'{toolbar(placeholder="Filter mods…")}'
                '<div class="table-wrap"><table class="data"><thead>'
                "<tr><th>Mod id</th></tr></thead><tbody>"
            )
            for m in ids:
                body += (
                    f'<tr data-filter-row data-filter-text="{esc(m)}">'
                    f'<td class="mono">{esc(m)}</td></tr>\n'
                )
            body += "</tbody></table></div>"
    body += "</section>"

    body += f"""
    <section>
      <h2>Datapack recipes only in {esc(pack_a)}</h2>
      <p class="section-note">Likely progression scripts to port into {esc(pack_b)}.</p>
"""
    if hints:
        body += (
            f'{toolbar(placeholder="Filter files…")}'
            '<div class="table-wrap"><table class="data"><thead>'
            "<tr><th>File</th></tr></thead><tbody>"
        )
        for h in hints:
            fpath = h.get("file") or ""
            body += (
                f'<tr data-filter-row data-filter-text="{esc(fpath)}">'
                f'<td class="mono">{esc(fpath)}</td></tr>\n'
            )
        body += "</tbody></table></div>"
    else:
        body += '<p class="empty">None detected.</p>'
    body += "</section>"

    body += f"""
    <section>
      <h2>KubeJS / datapack files only in {esc(pack_a)}</h2>
      <p class="section-note">{esc(len(kube.get("only_a") or []))} files (scripts + data).</p>
"""
    only_a = kube.get("only_a") or []
    if only_a:
        body += (
            f'{toolbar(placeholder="Filter…")}'
            '<div class="table-wrap"><table class="data"><thead>'
            "<tr><th>Relative path</th></tr></thead><tbody>"
        )
        for rel in only_a[:400]:
            body += (
                f'<tr data-filter-row data-filter-text="{esc(rel)}">'
                f'<td class="mono">{esc(rel)}</td></tr>\n'
            )
        body += "</tbody></table></div>"
        if len(only_a) > 400:
            body += f'<p class="empty">… +{len(only_a) - 400} more (see attribute.json)</p>'
    else:
        body += '<p class="empty">None.</p>'
    body += "</section>"

    only_pr = pr.get("only_a") or []
    body += f"<section><h2>Pack-origin recipe ids only in {esc(pack_a)}</h2>"
    if only_pr:
        body += (
            '<div class="table-wrap"><table class="data"><thead>'
            "<tr><th>Recipe id</th><th>Item</th><th>Type</th></tr></thead><tbody>"
        )
        for r in only_pr:
            body += (
                "<tr>"
                f'<td class="mono">{esc(r.get("id"))}</td>'
                f'<td class="item">{esc(r.get("item"))}</td>'
                f'<td class="mono">{esc(r.get("type"))}</td>'
                "</tr>\n"
            )
        body += "</tbody></table></div>"
    else:
        body += '<p class="empty">None (or dumps missing).</p>'
    body += "</section>"

    body += "<section><h2>Server config</h2>"
    if not sc.get("available_a") and not sc.get("available_b"):
        body += '<p class="empty">No dump configs yet — run make dump on both packs.</p>'
    else:
        body += (
            f'<p class="section-note">only {esc(pack_a)}={esc(len(sc.get("only_a") or []))} · '
            f'only {esc(pack_b)}={esc(len(sc.get("only_b") or []))} · '
            f'changed={esc(len(sc.get("changed") or []))}</p>'
        )
    body += "</section>"
    return body


def write_compare_site(pack_a: str, pack_b: str, *, all_packs: list[str] | None = None) -> Path:
    a = analyze_pack(pack_a)
    b = analyze_pack(pack_b)
    packs = all_packs if all_packs is not None else discover_dumped_packs()
    label_a = a["profile"].get("label") or pack_a
    label_b = b["profile"].get("label") or pack_b
    out_dir = HUB_ROOT / "compare" / f"{pack_a}-vs-{pack_b}"
    out_dir.mkdir(parents=True, exist_ok=True)
    HUB_ROOT.mkdir(parents=True, exist_ok=True)
    if not (HUB_ROOT / "assets").is_dir():
        copy_assets(HUB_ROOT)

    pages = [
        ("index.html", "Compare"),
        ("targets.html", "Targets"),
        ("pack-diff.html", "Pack recipes"),
        ("attribute.html", "Attribute"),
    ]
    assets = "../../assets"
    home = "../../index.html"
    switcher = pack_switcher_html(
        current=None, packs=packs, page="index.html", from_compare=True
    )
    attr = load_or_build_attribute(pack_a, pack_b)

    # Union of target ids (prefer A's order, then B-only)
    seen = set()
    union: list[str] = []
    for row in a["targets_all"] + b["targets_all"]:
        if row["id"] not in seen:
            seen.add(row["id"])
            union.append(row["id"])
    a_map = {r["id"]: r for r in a["targets_all"]}
    b_map = {r["id"]: r for r in b["targets_all"]}

    va = "ok" if a["verdict_ok"] else "fail"
    vb = "ok" if b["verdict_ok"] else "fail"

    body = f"""
    <header class="hero">
      <p class="kicker">Pack compare</p>
      <h1>{esc(pack_a)} vs {esc(pack_b)}</h1>
      <p class="lede">Reachability and pack-authored recipe differences under each pack's profile.</p>
    </header>
    <div class="compare-grid">
      <div class="compare-card">
        <h3>{esc(label_a)}</h3>
        <div class="verdict {va}">{"PLAYABLE" if a["verdict_ok"] else f'{len(a["targets_bad"])} blocked'}</div>
        <dl class="meta-row" style="margin-top:0.85rem">
          <span class="pair"><dt>targets</dt><dd>{esc(len(a["targets_ok"]))}/{esc(len(a["targets_all"]))} OK</dd></span>
          <span class="pair"><dt>pack recipes</dt><dd>{esc(len(a["pack_items"]))}</dd></span>
          <span class="pair"><dt>items</dt><dd>{esc(a["dump"].get("item_count"))}</dd></span>
        </dl>
        <p class="section-note" style="margin-top:0.75rem"><a href="../../packs/{esc(pack_a)}/index.html">Open {esc(pack_a)} report</a></p>
      </div>
      <div class="compare-card">
        <h3>{esc(label_b)}</h3>
        <div class="verdict {vb}">{"PLAYABLE" if b["verdict_ok"] else f'{len(b["targets_bad"])} blocked'}</div>
        <dl class="meta-row" style="margin-top:0.85rem">
          <span class="pair"><dt>targets</dt><dd>{esc(len(b["targets_ok"]))}/{esc(len(b["targets_all"]))} OK</dd></span>
          <span class="pair"><dt>pack recipes</dt><dd>{esc(len(b["pack_items"]))}</dd></span>
          <span class="pair"><dt>items</dt><dd>{esc(b["dump"].get("item_count"))}</dd></span>
        </dl>
        <p class="section-note" style="margin-top:0.75rem"><a href="../../packs/{esc(pack_b)}/index.html">Open {esc(pack_b)} report</a></p>
      </div>
    </div>

    <section>
      <h2>Target reachability</h2>
      <p class="section-note"><a href="targets.html">Full comparison table</a></p>
      {toolbar(fail=True, placeholder="Filter targets…")}
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr><th>Item</th><th>{esc(pack_a)}</th><th>{esc(pack_b)}</th></tr>
          </thead>
          <tbody>
"""
    for item in union:
        ra, rb = a_map.get(item), b_map.get(item)
        sa = "OK" if ra and ra["ok"] else ("FAIL" if ra else "—")
        sb = "OK" if rb and rb["ok"] else ("FAIL" if rb else "—")
        row_fail = (ra and not ra["ok"]) or (rb and not rb["ok"])
        status = "fail" if row_fail else "ok"
        da = str(ra["depth"]) if ra and ra["ok"] else sa
        db = str(rb["depth"]) if rb and rb["ok"] else sb
        filt = f"{item} {sa} {sb}".lower()
        body += (
            f'<tr class="{status}-row" data-filter-row data-status="{status}" '
            f'data-filter-text="{esc(filt)}">'
            f'<td class="item">{esc(item)}</td>'
            f'<td class="mono">{esc(da if ra and ra["ok"] else sa)}</td>'
            f'<td class="mono">{esc(db if rb and rb["ok"] else sb)}</td>'
            f"</tr>\n"
        )
    body += "</tbody></table></div></section>"

    body += f"""
    <section>
      <h2>Pack-only recipes in {esc(pack_a)}</h2>
      <p class="section-note">
        Items with pack-origin routes in {esc(pack_a)} that are missing or differ in {esc(pack_b)}.
        <a href="pack-diff.html">Full diff</a>
      </p>
    </section>
"""
    if attr:
        body += attribute_section_html(attr, pack_a, pack_b)
    else:
        body += (
            '<section><h2>Source attribute</h2>'
            '<p class="empty">Run <code>make attribute A='
            f"{esc(pack_a)} B={esc(pack_b)}</code> "
            "(packs must be registered with <code>make add</code>).</p></section>"
        )
    render_page(
        title=f"{pack_a} vs {pack_b}",
        nav=nav_links("index.html", pages),
        body=body,
        out=out_dir / "index.html",
        assets_rel=assets,
        home=home,
        pack_switcher=switcher,
    )

    # targets detail page
    tbody = f"""
    <header class="hero">
      <p class="kicker">Compare</p>
      <h1>Targets — {esc(pack_a)} vs {esc(pack_b)}</h1>
    </header>
    {toolbar(fail=True, placeholder="Filter…")}
    <div class="table-wrap">
      <table class="data">
        <thead>
          <tr>
            <th>Item</th>
            <th>{esc(pack_a)} status</th>
            <th>Depth</th>
            <th>{esc(pack_b)} status</th>
            <th>Depth</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
"""
    for item in union:
        ra, rb = a_map.get(item), b_map.get(item)
        why = (ra or rb or {}).get("why", "") if (ra or rb) else ""
        if ra:
            why = ra.get("why") or why
        elif rb:
            why = rb.get("why") or why
        sa_ok = bool(ra and ra["ok"])
        sb_ok = bool(rb and rb["ok"])
        row_fail = (ra and not ra["ok"]) or (rb and not rb["ok"])
        status = "fail" if row_fail else "ok"
        filt = f"{item} {why}".lower()
        tbody += (
            f'<tr class="{status}-row" data-filter-row data-status="{status}" '
            f'data-filter-text="{esc(filt)}">'
            f'<td class="item">{esc(item)}</td>'
            f'<td class="status">{"OK" if sa_ok else ("FAIL" if ra else "—")}</td>'
            f'<td class="depth">{esc(ra["depth"] if sa_ok else "—")}</td>'
            f'<td class="status">{"OK" if sb_ok else ("FAIL" if rb else "—")}</td>'
            f'<td class="depth">{esc(rb["depth"] if sb_ok else "—")}</td>'
            f'<td class="why">{esc(why)}</td>'
            f"</tr>\n"
        )
    tbody += "</tbody></table></div>"
    render_page(
        title=f"Targets — {pack_a} vs {pack_b}",
        nav=nav_links("targets.html", pages),
        body=tbody,
        out=out_dir / "targets.html",
        assets_rel=assets,
        home=home,
        pack_switcher=switcher,
    )

    # pack recipe diff
    pbody = f"""
    <header class="hero">
      <p class="kicker">Compare</p>
      <h1>Pack recipes — {esc(pack_a)} vs {esc(pack_b)}</h1>
      <p class="lede">Pack-origin routes present in one pack but not the other.</p>
    </header>
    {toolbar(placeholder="Filter…")}
"""
    rows_html = []
    all_items = sorted({i for i, _ in a["pack_items"]} | {i for i, _ in b["pack_items"]})
    for item in all_items:
        ra = _routes(a["dump"], item)
        rb = _routes(b["dump"], item)
        pack_a_routes = [e for e in ra if e.get("origin") == "pack"]
        pack_b_routes = [e for e in rb if e.get("origin") == "pack"]
        ids_b = {e.get("id") for e in rb}
        ids_a = {e.get("id") for e in ra}
        only_a = [e for e in pack_a_routes if e.get("id") not in ids_b]
        only_b = [e for e in pack_b_routes if e.get("id") not in ids_a]
        if not only_a and not only_b:
            continue
        for e in only_a:
            filt = f"{item} {e.get('id')} {pack_a}".lower()
            rows_html.append(
                f'<tr data-filter-row data-origin="pack" data-filter-text="{esc(filt)}">'
                f'<td class="item">{esc(item)}</td>'
                f'<td><span class="badge pack">only {esc(pack_a)}</span></td>'
                f'<td class="mono">{esc(e.get("id"))}</td>'
                f'<td class="mono">{esc(e.get("type"))}</td>'
                f"</tr>\n"
            )
        for e in only_b:
            filt = f"{item} {e.get('id')} {pack_b}".lower()
            rows_html.append(
                f'<tr data-filter-row data-origin="pack" data-filter-text="{esc(filt)}">'
                f'<td class="item">{esc(item)}</td>'
                f'<td><span class="badge pack">only {esc(pack_b)}</span></td>'
                f'<td class="mono">{esc(e.get("id"))}</td>'
                f'<td class="mono">{esc(e.get("type"))}</td>'
                f"</tr>\n"
            )

    if rows_html:
        pbody += (
            '<div class="table-wrap"><table class="data"><thead>'
            "<tr><th>Item</th><th>Diff</th><th>Recipe id</th><th>Type</th></tr>"
            "</thead><tbody>"
            + "".join(rows_html)
            + "</tbody></table></div>"
        )
    else:
        pbody += '<p class="empty">No pack-origin recipe differences found.</p>'

    render_page(
        title=f"Pack recipes — {pack_a} vs {pack_b}",
        nav=nav_links("pack-diff.html", pages),
        body=pbody,
        out=out_dir / "pack-diff.html",
        assets_rel=assets,
        home=home,
        pack_switcher=switcher,
    )

    if attr:
        render_page(
            title=f"Attribute — {pack_a} vs {pack_b}",
            nav=nav_links("attribute.html", pages),
            body=attribute_page_html(attr, pack_a, pack_b),
            out=out_dir / "attribute.html",
            assets_rel=assets,
            home=home,
            pack_switcher=switcher,
        )

    print(f"wrote {out_dir}/")
    return out_dir


def write_all() -> Path:
    packs = discover_dumped_packs()
    for pid in packs:
        write_pack_site(pid, all_packs=packs)
    # pairwise compares for hub links
    for i, a in enumerate(packs):
        for b in packs[i + 1 :]:
            write_compare_site(a, b, all_packs=packs)
    return write_hub(packs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--all", action="store_true", help="hub + every dumped pack (default)")
    g.add_argument("--pack", help="one pack id + refresh hub")
    g.add_argument(
        "--compare",
        nargs=2,
        metavar=("A", "B"),
        help="compare two packs into the hub",
    )
    a = ap.parse_args()
    try:
        if a.compare:
            packs = discover_dumped_packs()
            write_compare_site(a.compare[0], a.compare[1], all_packs=packs)
            write_hub(packs)
        elif a.pack:
            packs = discover_dumped_packs()
            write_pack_site(a.pack, all_packs=packs)
            write_hub(packs)
        else:
            # --all or bare invocation
            write_all()
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"hub: {HUB_ROOT / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
