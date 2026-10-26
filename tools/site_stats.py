"""Compute the numbers shown on the project website from the project repository's files.

Usage (standard library only, no installs):
    python tools/site_stats.py --repo PATH/TO/project_fyp            # print JSON
    python tools/site_stats.py --repo PATH/TO/project_fyp --write    # also paste it into index.html

PATH/TO/project_fyp is a git checkout of https://github.com/Viritha-D/project_fyp.
The JSON printed on stdout is exactly what goes between /* SITE_DATA_START */ and
/* SITE_DATA_END */ in index.html; --write does that replacement for you. A report of
mismatches between files and of venue evidence is printed on stderr; read it each time.

How things are identified
- A paper is one source PDF: a distinct value of Source_File in the master table.
  (Paper-ID stems such as P2021_143 and distinct titles are also reported, as a cross-check.)
- A record is one row of papers_master_with_matching_text.csv.
- Venues come only from VENUE_MAP below. A group whose entry is None is shown as
  "venue to be confirmed". Repo evidence about venues is printed under "venue_evidence"
  so the map can be filled in, but it is never shown on the page by itself.
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

# Fill in a venue (one of VENUE_NAMES' keys) to confirm it; None means "venue to be confirmed".
# Groups: rows whose paper_id has no venue tag are grouped by the year file they came from
# (P2019_... -> "2019 file"); rows whose paper_id carries a tag (P2015_FOGA_...) are grouped by it.
VENUE_MAP = {
    "2019 file": None, "2020 file": None, "2021 file": None,
    "2022 file": None, "2023 file": None, "2024 file": None,
    "a/b/c/d files": "PReMI",
    "FOGA rows": None, "PPSN rows": None, "GECCO rows": None,
}
VENUE_NAMES = {
    "CEC": "IEEE Congress on Evolutionary Computation",
    "GECCO": "Genetic and Evolutionary Computation Conference",
    "PPSN": "Parallel Problem Solving from Nature",
    "FOGA": "Foundations of Genetic Algorithms",
    "PReMI": "Pattern Recognition and Machine Intelligence",
}
TAG_GROUP = {"PReMI": "a/b/c/d files"}  # PReMI rows came from the a/b/c/d files

REPO_URL = "https://github.com/Viritha-D/project_fyp"
MASTER = "papers_master_with_matching_text.csv"
EMBED_REF = "papers_master_with_embeddings_ref.csv"
EMBED_META = "embedding_metadata.json"
CLEAN = "master_dataset_clean.csv"
ENTITIES = ["problem_entities_enriched.json", "problem_entities.json"]  # first one present wins
ENTITY_MAP = "paper_to_entity_map_final.csv"
STRATEGIES = "entity_strategy_layer_v2.csv"
INGEST_LOG = "ingest_log.csv"
EVAL = "part9_eval_results.json"

SAMPLE_COLS = ["paper_id", "Year", "Category", "Benchmark_Name", "Algorithm_Name",
               "Performance_Metric", "Is_Optimal_Found"]

csv.field_size_limit(2**31 - 1)


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def csv_header(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh))


def git(repo, *args):
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def venue_tag(paper_id):
    m = re.match(r"P\d{4}_([A-Za-z]+)_", paper_id)
    return m.group(1) if m else None


def group_of(paper_id):
    tag = venue_tag(paper_id)
    if tag:
        return TAG_GROUP.get(tag, f"{tag} rows")
    return f"{paper_id[1:5]} file"


def paper_stem(paper_id):
    return re.sub(r"_Ext_\d+$", "", paper_id)


def year_span(years):
    ys = sorted(int(y) for y in years if str(y).isdigit())
    return f"{ys[0]}–{ys[-1]}" if ys else None


def pick_samples(rows, n=6):
    """Short, varied rows: every shown field reported and at most 40 characters. Earlier passes
    insist on a new year and a new (Category, outcome) pair; no paper, benchmark or algorithm twice.
    Rows whose paper_id carries a venue tag are skipped, so no unconfirmed venue appears on the page."""
    def ok(r):
        return (not venue_tag(r["paper_id"])
                and all(r[c] and r[c] != "Not Reported" and len(r[c]) <= 40 for c in SAMPLE_COLS))
    pool = sorted((r for r in rows if ok(r)), key=lambda r: r["paper_id"])
    picked, seen = [], defaultdict(set)
    for need_year, need_combo in ((True, True), (True, False), (False, False)):
        for r in pool:
            if len(picked) >= n:
                break
            combo = (r["Category"], r["Is_Optimal_Found"])
            if (paper_stem(r["paper_id"]) in seen["paper"] or norm(r["Benchmark_Name"]) in seen["bench"]
                    or norm(r["Algorithm_Name"]) in seen["algo"]
                    or (need_year and r["Year"] in seen["year"]) or (need_combo and combo in seen["combo"])):
                continue
            picked.append(r)
            seen["paper"].add(paper_stem(r["paper_id"])); seen["bench"].add(norm(r["Benchmark_Name"]))
            seen["algo"].add(norm(r["Algorithm_Name"])); seen["year"].add(r["Year"]); seen["combo"].add(combo)
    return [{c: r[c] for c in SAMPLE_COLS} for r in sorted(picked, key=lambda r: r["paper_id"])]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="../project_fyp", help="path to a project_fyp checkout")
    ap.add_argument("--write", action="store_true", help="replace the SITE_DATA block in index.html")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    sys.stderr.reconfigure(encoding="utf-8")
    repo = Path(args.repo).resolve()
    if not (repo / MASTER).exists():
        sys.exit(f"{MASTER} not found in {repo}; pass --repo PATH/TO/project_fyp")

    tracked = set(git(repo, "ls-files").splitlines())
    commit = git(repo, "log", "-1", "--format=%h %cs")
    def committed(f):
        return git(repo, "log", "-1", "--format=%cs", "--", f) or None
    checks = []

    # ---- master table ----
    master = read_csv(repo / MASTER)
    n_records = len(master)
    papers = {r["Source_File"] for r in master}
    stems = {paper_stem(r["paper_id"]) for r in master}
    titles = {norm(r["Paper_Title"]) for r in master}
    if len(stems) != len(papers) or len(titles) != len(papers):
        checks.append(f"Paper identity: {len(papers)} distinct Source_File PDFs, {len(stems)} paper-ID "
                      f"stems, {len(titles)} distinct titles in {MASTER}; the site counts PDFs.")

    # ---- other pipeline files ----
    n_embedded = len(read_csv(repo / EMBED_REF)) if (repo / EMBED_REF).exists() else None
    meta = json.loads((repo / EMBED_META).read_text(encoding="utf-8")) if (repo / EMBED_META).exists() else {}
    ent_file = next(f for f in ENTITIES if (repo / f).exists())
    entities = json.loads((repo / ent_file).read_text(encoding="utf-8"))
    ent_ids = {e["entity_id"] for e in entities}
    emap = read_csv(repo / ENTITY_MAP)
    strat = read_csv(repo / STRATEGIES)
    strat_ids = {r["entity_id"] for r in strat}
    map_ids = {r["entity_id"] for r in emap}
    for label, n in [(EMBED_REF, n_embedded), (EMBED_META + " n_papers_embedded", meta.get("n_papers_embedded")),
                     (ENTITY_MAP, len(emap))]:
        if n is not None and n != n_records:
            checks.append(f"{label} has {n} rows but {MASTER} has {n_records}.")
    if strat_ids - ent_ids:
        checks.append(f"{STRATEGIES} references {len(strat_ids - ent_ids)} entity id(s) not in {ent_file}: "
                      f"{sorted(strat_ids - ent_ids)}.")
    if map_ids - ent_ids:
        checks.append(f"{ENTITY_MAP} references {len(map_ids - ent_ids)} entity id(s) not in {ent_file}: "
                      f"{sorted(map_ids - ent_ids)}.")
    built_from = len([r for r in emap if r["entity_id"] in ent_ids])

    # ---- cleaned table that may be ahead of the master ----
    clean = read_csv(repo / CLEAN) if (repo / CLEAN).exists() else []
    master_titles = titles
    clean_new = [r for r in clean if norm(r["Paper_Title"]) not in master_titles]
    if clean:
        checks.append(f"{CLEAN} ({committed(CLEAN)}) has {len(clean)} cleaned rows; {len(clean_new)} of them "
                      f"({len({r['Source_File'] for r in clean_new})} PDFs) have a title not in {MASTER} "
                      f"({committed(MASTER)}), so they are not yet embedded, grouped or ranked.")
    ingest = read_csv(repo / INGEST_LOG) if (repo / INGEST_LOG).exists() else None
    if ingest is None:
        checks.append(f"{INGEST_LOG} is not in the repository, so source labels for the a/b/c/d files "
                      f"could not be read from it.")

    # ---- venues ----
    groups = defaultdict(list)
    for r in master:
        groups[group_of(r["paper_id"])].append(r)
    for g in groups:
        if g not in VENUE_MAP:
            checks.append(f"Group '{g}' is not in VENUE_MAP; shown as venue to be confirmed.")
    clean_conf_by_title = defaultdict(Counter)
    for r in clean:
        clean_conf_by_title[norm(r["Paper_Title"])][r.get("Conference", "")] += 1
    venue_rows, evidence, pending = defaultdict(list), {}, []
    for g, rows in sorted(groups.items()):
        venue = VENUE_MAP.get(g)
        venue_rows[venue or "venue to be confirmed"].extend(rows)
        joined = Counter()
        for r in rows:
            confs = clean_conf_by_title.get(norm(r["Paper_Title"]))
            joined[" / ".join(sorted(confs)) if confs else "no title match"] += 1
        evidence[g] = {"records": len(rows), "papers": len({r["Source_File"] for r in rows}),
                       "years": year_span(r["Year"] for r in rows), "confirmed_venue": venue,
                       "paper_id_tag": venue_tag(rows[0]["paper_id"]),
                       f"{CLEAN} Conference, joined by title": dict(joined)}
        if not venue:
            pending.append(g)
    sources = []
    for v, rows in venue_rows.items():
        sources.append({"venue": v, "name": VENUE_NAMES.get(v), "papers": len({r["Source_File"] for r in rows}),
                        "records": len(rows), "years": year_span(r["Year"] for r in rows)})
    sources.sort(key=lambda s: (s["venue"] == "venue to be confirmed", -s["records"]))
    for v in sorted({v for v in VENUE_MAP.values() if v} - set(venue_rows)):
        rows = [r for r in clean if r.get("Conference") == v]
        sources.append({"venue": v, "name": VENUE_NAMES.get(v), "papers": 0, "records": 0, "years": None,
                        "not_in_master": {"file": CLEAN, "records": len(rows),
                                          "papers": len({r["Source_File"] for r in rows}),
                                          "years": year_span(r["Year"] for r in rows)}})
        checks.append(f"{v}: 0 rows in {MASTER}; {len(rows)} rows in {CLEAN}.")

    # ---- entities ----
    by_name = {e["canonical_name"]: e for e in entities}
    def entity_example(e):
        return {"name": e["canonical_name"], "type": e["entity_type"], "papers": e["n_supporting_papers"],
                "n_names": len(e["aliases"]["benchmark_names"]), "names": e["aliases"]["benchmark_names"][:6]}
    examples = [entity_example(by_name[n]) for n in ["CEC 2017 benchmark test suite", "Rastrigin"] if n in by_name]
    subsets = sorted((e for e in entities if e["entity_type"] == "named_subset"),
                     key=lambda e: (-e["n_supporting_papers"], e["canonical_name"]))
    if subsets:
        examples.append(entity_example(subsets[0]))

    # ---- strategy example: Rastrigin's best-covered metric family ----
    ex_ent = by_name.get("Rastrigin") or max(entities, key=lambda e: e["n_supporting_papers"])
    ex_rows = [r for r in strat if r["entity_id"] == ex_ent["entity_id"]]
    fam = Counter(r["metric_family"] for r in ex_rows).most_common(1)[0][0]
    fam_rows = sorted((r for r in ex_rows if r["metric_family"] == fam), key=lambda r: int(r["rank_within_metric"]))
    def pct(v):
        return None if v in ("", None) else round(float(v), 1)
    strategy_example = {
        "entity": ex_ent["canonical_name"], "metric_family": fam, "total_rows": len(fam_rows),
        "rows": [{"rank": int(r["rank_within_metric"]), "strategy": r["strategy"],
                  "papers_reporting": int(float(r["n_papers_reporting"])),
                  "reports_with_optimum_status": int(float(r["n_papers_reporting_optimal_status"])),
                  "pct_optimum_found": pct(r["pct_optimal_found_among_reported"])} for r in fam_rows[:6]],
    }

    # ---- evaluation (Part 9), reported for checking only ----
    evaluation = None
    if (repo / EVAL).exists():
        ev = json.loads((repo / EVAL).read_text(encoding="utf-8"))
        scored = [x for x in ev if x["difficulty"] != "out_of_scope" and x["correct"] is not None]
        oos = [x for x in ev if x["difficulty"] == "out_of_scope"]
        evaluation = {"file": EVAL, "committed": committed(EVAL), "queries": len(ev),
                      "in_scope_scored": len(scored), "in_scope_correct": sum(1 for x in scored if x["correct"]),
                      "in_scope_unscored": sum(1 for x in ev if x["difficulty"] != "out_of_scope" and x["correct"] is None),
                      "out_of_scope": len(oos), "out_of_scope_rejected": sum(1 for x in oos if x["correct"])}
        evaluation["overall_correct_of_scored"] = [evaluation["in_scope_correct"] + evaluation["out_of_scope_rejected"],
                                                   evaluation["in_scope_scored"] + evaluation["out_of_scope"]]

    # ---- cleaned corpus by year and venue (the Conference column of the cleaned table) ----
    corpus = None
    if clean:
        venues = [v for v, _ in Counter(r["Conference"] for r in clean).most_common()]
        by_year = defaultdict(Counter)
        for r in clean:
            y = r["Year"]
            by_year["≤2014" if y.isdigit() and int(y) <= 2014 else y][r["Conference"]] += 1
        corpus = {
            "file": CLEAN, "committed": committed(CLEAN), "records": len(clean),
            "by_category": dict(Counter(r["Category"] for r in clean).most_common()),
            "venues": venues,
            "by_venue": {v: {"records": sum(1 for r in clean if r["Conference"] == v),
                             "years": year_span(r["Year"] for r in clean if r["Conference"] == v)} for v in venues},
            "by_year": [{"year": y, **{v: by_year[y][v] for v in venues}}
                        for y in sorted(by_year, key=lambda y: (y != "≤2014", y))],
        }

    data = {
        "as_of": max(filter(None, [committed(f) for f in [MASTER, ent_file, STRATEGIES, CLEAN]])),
        "generated": date.today().isoformat(),
        "repo": {"url": REPO_URL, "commit": commit},
        "papers": {"value": len(papers), "file": MASTER, "rule": "distinct Source_File (one PDF = one paper)",
                   "paper_id_stems": len(stems), "distinct_titles": len(titles)},
        "records": {"value": n_records, "file": MASTER, "committed": committed(MASTER),
                    "csv_url": f"{REPO_URL}/blob/main/{MASTER}" if MASTER in tracked else None,
                    "columns": csv_header(repo / MASTER), "samples": pick_samples(master)},
        "entities": {"value": len(entities), "file": ent_file, "committed": committed(ent_file),
                     "by_type": dict(Counter(e["entity_type"] for e in entities).most_common()),
                     "by_category": dict(Counter(e["category"] for e in entities).most_common()),
                     "examples": examples},
        "strategies": {"value": len(strat), "file": STRATEGIES, "committed": committed(STRATEGIES),
                       "entities_covered": len(strat_ids & ent_ids), "example": strategy_example},
        "stage": {"embedded": n_embedded, "embedding_model": meta.get("model_name"),
                  "built_from": built_from, "master_records": n_records,
                  "clean_file": CLEAN if clean else None, "clean_committed": committed(CLEAN) if clean else None,
                  "clean_records": len(clean), "clean_records_not_in_master": len(clean_new),
                  "clean_papers_not_in_master": len({r["Source_File"] for r in clean_new})},
        "sources": sources,
        "evaluation": evaluation,
        "corpus": corpus,
    }
    # The report goes to stderr so that stdout is only the page block; venue evidence and the
    # pending group names never reach the page, because they name venues VENUE_MAP has not confirmed.
    report = {"checks": checks, "venues_pending": pending, "venue_evidence": evidence}
    print(json.dumps(report, ensure_ascii=False, indent=1), file=sys.stderr)
    out = json.dumps(data, ensure_ascii=False, indent=1)
    # Safe inside a <script> element: no "</script>", no "<!--", no line/paragraph separators.
    out = out.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    print(out)

    if args.write:
        page = Path(__file__).resolve().parent.parent / "index.html"
        html = page.read_text(encoding="utf-8")
        start, end = "/* SITE_DATA_START */", "/* SITE_DATA_END */"
        a, b = html.index(start) + len(start), html.index(end)
        page.write_text(html[:a] + out + html[b:], encoding="utf-8")
        print(f"Wrote SITE_DATA into {page}", file=sys.stderr)


if __name__ == "__main__":
    main()
