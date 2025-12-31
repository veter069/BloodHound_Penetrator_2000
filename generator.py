#!/usr/bin/env python3
# generator.py
# FIXED: Dataview table shows task title (including wikilink) correctly.
# Keeps: Status / Task / Comment. Task is an active link to Notes heading (hover preview in-vault).

import json
import os
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from neo4j import GraphDatabase

logging.getLogger("neo4j").setLevel(logging.ERROR)
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)


@dataclass
class QuerySpec:
    id: str
    name: str
    description: str
    cypher: str
    qtype: str = "Nodes"
    self_check: bool = False
    severity: str = ""
    category: str = ""
    tags: List[str] = field(default_factory=list)


def load_queries(path: str) -> List[QuerySpec]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "queries" in raw:
        items = raw["queries"]
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError(f"Unsupported queries format in {path}")

    out: List[QuerySpec] = []
    for i, q in enumerate(items):
        if not isinstance(q, dict):
            continue

        tags = q.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if not isinstance(tags, list):
            tags = []

        out.append(
            QuerySpec(
                id=str(q.get("id", i)),
                name=q.get("name", f"Query {i}"),
                description=q.get("description", ""),
                cypher=q.get("query", ""),
                qtype=q.get("type", "Nodes"),
                self_check=bool(q.get("selfcheck", False)),
                severity=q.get("severity", ""),
                category=q.get("category", ""),
                tags=tags,
            )
        )
    return out


def run_cypher(driver, cypher: str) -> List[Dict[str, Any]]:
    with driver.session() as session:
        result = session.run(cypher)
        return [r.data() for r in result]


def format_rows_md(records: List[Dict[str, Any]], limit: int = 50) -> str:
    if not records:
        return "_Нет результатов._"

    keys = list(records[0].keys())
    if len(keys) == 1:
        k = keys[0]
        rows = [f"- {r.get(k)}" for r in records[:limit]]
        tail = "" if len(records) <= limit else f"\n…и ещё {len(records)-limit} строк(и)."
        return "\n".join(rows) + tail

    header = "| " + " | ".join(keys) + " |"
    sep = "| " + " | ".join(["---"] * len(keys)) + " |"
    body = []
    for r in records[:limit]:
        body.append("| " + " | ".join(str(r.get(k, "")) for k in keys) + " |")
    tail = "" if len(records) <= limit else f"\n\n…и ещё {len(records)-limit} строк(и)."
    return "\n".join([header, sep] + body) + tail


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\r", " ").replace("\n", " ")).strip()


def render_task(q: QuerySpec, has_result: bool, notes_file_stem: str) -> str:
    # Semantics as before
    if not has_result:
        checkbox = "x"
        state = "провал"
    elif q.self_check:
        checkbox = "x"
        state = "успех"
    else:
        checkbox = " "
        state = "na"

    desc = _one_line(q.description)

    # Active link in the TITLE so Dataview can render it and show hover preview
    task_link = f"[[{notes_file_stem}#{q.name}|{q.name}]]"

    # comments is meant to be edited manually in the checklist note
    return (
        f"- [{checkbox}] {task_link}  "
        f"state:: {state}  "
        f"comments:: -\n"
        f"  - {desc}\n"
    )


def render_note(q: QuerySpec, records: List[Dict[str, Any]], limit: int) -> str:
    return (
        f"## {q.name}\n\n"
        f"Описание:  {q.description}\n\n"
        f"Cypher запрос:\n\n"
        f"```cypher\n{q.cypher}\n```\n\n"
        f"Всего записей: {len(records)}\n\n"
        f"Результат\n\n"
        f"{format_rows_md(records, limit=limit)}\n\n---\n\n"
    )


def make_dataview(ts: str) -> str:
    # The key fix: do NOT use task.name (it can be empty for link-titles in some cases).
    # Instead, take task.text and cut off inline fields (state/comments) so the cell is clean.
    return f"""# Трекинг задач BloodHound ({ts})

## Незавершенные задачи

```dataview
TABLE WITHOUT ID
  choice(task.completed, "🟢", "⚪️") AS "Статус",
  regexreplace(task.text, "\\\\s+state::.*$", "") AS "Задача",
  task.comments AS "Комментарий"
FROM #checklist
FLATTEN file.tasks AS task
WHERE task.completed = false
```

---

## Все задачи

```dataview
TABLE WITHOUT ID
  choice(task.completed, "🟢", "⚪️") AS "Статус",
  regexreplace(task.text, "\\\\s+state::.*$", "") AS "Задача",
  task.comments AS "Комментарий"
FROM #checklist
FLATTEN file.tasks AS task
```

---

## Статистика

```dataview
TABLE WITHOUT ID 
  (length(filter(file.tasks.completed, (t) => t = true))) AS Завершённых,
  (length(file.tasks.text)) - (length(filter(file.tasks.completed, (t) => t = true))) AS "Незавершенных",
  (length(filter(file.tasks.completed, (t) => t = true))) / (length(file.tasks.text)) * 100 AS "% Завершено",
  (length(file.tasks.text)) AS Всего
FROM #checklist 
```
"""


def generate():
    load_dotenv()

    uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd = os.getenv("NEO4J_PASS", "neo4j")

    queries_file = os.getenv("QUERIES_FILE", "./queries.json")
    owned_file = os.getenv("OWNED_QUERIES_FILE", "./ownedqueries.json")

    out_dir = Path(os.getenv("OBSIDIAN_OUT", "./output"))
    out_dir.mkdir(parents=True, exist_ok=True)

    max_rows = int(os.getenv("MAX_ROWS", "50"))

    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    checklist_path = out_dir / f"BloodHound_Checklist_{ts}.md"
    notes_path = out_dir / f"BloodHound_Notes_{ts}.md"
    tracking_path = out_dir / f"BloodHound_Tracking_{ts}.md"

    queries = [q for q in load_queries(queries_file) if (q.cypher or "").strip()]
    owned = [q for q in load_queries(owned_file) if (q.cypher or "").strip()]

    total = len(queries) + len(owned)
    idx = 0
    errors = 0

    def progress(prefix: str, name: str, i: int, total_count: int):
        print(f"[#] {i}/{total_count} {prefix}: {name}", flush=True)

    driver = GraphDatabase.driver(uri, auth=(user, pwd))

    checklist = [
        f"# BloodHound чек-лист ({ts})\n",
        "#checklist\n\n",
    ]
    notes = [f"# BloodHound заметки ({ts})\n\n"]

    notes_file_stem = notes_path.stem

    for block, qlist in (
        ("Общие проверки", queries),
        ("Проверки от owned=TRUE", owned),
    ):
        checklist.append(f"## {block}\n")
        notes.append(f"# {block}\n\n")

        for q in qlist:
            idx += 1
            progress(block, q.name, idx, total)

            try:
                records = run_cypher(driver, q.cypher)
                has_result = len(records) > 0
            except Exception as e:
                errors += 1
                records = [{"error": str(e)}]
                has_result = True

            checklist.append(render_task(q, has_result, notes_file_stem))
            notes.append(render_note(q, records, limit=max_rows))

    driver.close()

    checklist_path.write_text("".join(checklist), encoding="utf-8")
    notes_path.write_text("".join(notes), encoding="utf-8")
    tracking_path.write_text(make_dataview(ts), encoding="utf-8")

    print(f"[+] Done: {idx}/{total} | Errors: {errors}", flush=True)
    print(f"[+] {checklist_path}", flush=True)
    print(f"[+] {notes_path}", flush=True)
    print(f"[+] {tracking_path}", flush=True)


if __name__ == "__main__":
    generate()
