#!/usr/bin/env python3
"""Generates the synthetic file corpus, metadata DB, and access log from scratch.

    python data/generate_synthetic_data.py

Reproducible: same --seed produces the same file plan, filenames, topics, and access
log *structure* (session composition, which files recur, relative timestamp deltas).
Absolute timestamps are anchored to "now" at run time (not frozen to the seed) so the
personalization layer's recency/"it's Monday morning" features stay meaningful whenever
this is demoed — see data/synth/access_log.py for that tradeoff.

Content generation uses the Gemini API (app/llm_client.py) when GEMINI_API_KEY is set,
for non-repetitive realistic prose; otherwise falls back to the seeded template
generator in data/synth/content.py. Either way every file written is real: real .docx,
real .xlsx, real .pptx, real .pdf, real .png, on disk under data/files_corpus/.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from random import Random

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from app.models import FileRecord, UserRecord  # noqa: E402
from data.synth import content, corpus_writer  # noqa: E402
from data.synth.access_log import simulate_access_log  # noqa: E402
from data.synth.personas import PERSONAS  # noqa: E402
from data.synth.topics import TOPICS  # noqa: E402

DESCRIPTORS = [
    "notes", "draft", "report", "summary", "analysis", "update", "review",
    "plan", "log", "final", "working", "v2", "overview", "checklist",
]

TABULAR_TYPES = {"xlsx"}
SLIDE_TYPES = {"pptx"}
IMAGE_TYPES = {"png"}
CODE_TYPES = {"py"}
TEXT_NATIVE_TYPES = {"md", "txt", "docx", "pdf"}


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def pick_file_type(topic, rng: Random) -> str:
    types = list(topic.file_type_weights.keys())
    weights = list(topic.file_type_weights.values())
    return rng.choices(types, weights=weights, k=1)[0]


def make_filename(topic, file_type: str, rng: Random, used: set[str]) -> str:
    for _ in range(20):
        keyword = rng.choice(topic.keywords)
        descriptor = rng.choice(DESCRIPTORS)
        base = f"{slugify(keyword)}_{descriptor}"
        candidate = f"{base}.{file_type}"
        if candidate not in used:
            used.add(candidate)
            return candidate
    # extremely unlikely fallback: disambiguate with a counter
    counter = len(used)
    candidate = f"{slugify(topic.slug)}_{counter}.{file_type}"
    used.add(candidate)
    return candidate


def random_timestamps(rng: Random, now: datetime) -> tuple[datetime, datetime]:
    created_days_ago = rng.randint(14, 540)
    created_at = now - timedelta(days=created_days_ago, hours=rng.randint(0, 23))
    modified_days_after = rng.randint(0, min(created_days_ago, 60))
    modified_at = created_at + timedelta(days=modified_days_after, hours=rng.randint(0, 23))
    if modified_at > now:
        modified_at = now
    return created_at, modified_at


def generate_content_for(topic, filename: str, file_type: str, rng: Random, use_llm: bool):
    if use_llm and file_type in TEXT_NATIVE_TYPES:
        llm_result = content.generate_llm_prose(topic, filename, file_type)
        if llm_result is not None:
            return llm_result, None, None

    if file_type in CODE_TYPES:
        return content.generate_code(topic, filename, rng), None, None
    if file_type in TABULAR_TYPES:
        rows, flattened = content.generate_table(topic, filename, rng)
        gc = content.GeneratedContent(display_text=flattened, extracted_text=flattened)
        return gc, rows, None
    if file_type in SLIDE_TYPES:
        slides, flattened = content.generate_slides(topic, filename, rng)
        gc = content.GeneratedContent(display_text=flattened, extracted_text=flattened)
        return gc, None, slides
    if file_type in IMAGE_TYPES:
        caption = content.generate_image_caption(topic, filename, rng)
        gc = content.GeneratedContent(display_text=caption, extracted_text=caption)
        return gc, None, None
    # md / txt / docx / pdf template fallback
    if file_type in ("txt",) or rng.random() < 0.4:
        return content.generate_notes(topic, filename, rng), None, None
    return content.generate_prose(topic, filename, rng), None, None


def write_to_disk(path: Path, file_type: str, title: str, gc: content.GeneratedContent, rows, slides, rng: Random):
    path.parent.mkdir(parents=True, exist_ok=True)
    if file_type == "py":
        corpus_writer.write_py(path, gc.display_text)
    elif file_type == "md":
        corpus_writer.write_md(path, gc.display_text)
    elif file_type == "txt":
        corpus_writer.write_txt(path, gc.display_text)
    elif file_type == "docx":
        corpus_writer.write_docx(path, title, gc.display_text)
    elif file_type == "pdf":
        corpus_writer.write_pdf(path, title, gc.display_text)
    elif file_type == "xlsx":
        corpus_writer.write_xlsx(path, rows)
    elif file_type == "pptx":
        corpus_writer.write_pptx(path, slides)
    elif file_type == "png":
        corpus_writer.write_png(path, gc.display_text, rng)
    else:
        raise ValueError(f"unknown file_type {file_type}")


def build_file_plan(num_files: int, seed: int, corpus_dir: Path, now: datetime, use_llm: bool) -> list[FileRecord]:
    rng = Random(seed)
    per_topic = num_files // len(TOPICS)
    remainder = num_files - per_topic * len(TOPICS)

    records: list[FileRecord] = []
    used_filenames: set[str] = set()

    for i, topic in enumerate(TOPICS):
        count = per_topic + (1 if i < remainder else 0)
        topic_used: set[str] = set()
        for _ in range(count):
            file_type = pick_file_type(topic, rng)
            filename = make_filename(topic, file_type, rng, topic_used)
            title = filename.rsplit(".", 1)[0].replace("_", " ").title()
            gc, rows, slides = generate_content_for(topic, filename, file_type, rng, use_llm)

            rel_path = f"{topic.slug}/{filename}"
            abs_path = corpus_dir / rel_path
            write_to_disk(abs_path, file_type, title, gc, rows, slides, rng)

            created_at, modified_at = random_timestamps(rng, now)
            size_bytes = abs_path.stat().st_size

            records.append(
                FileRecord(
                    filename=filename,
                    path=rel_path,
                    file_type=file_type,
                    size_bytes=size_bytes,
                    created_at=created_at,
                    modified_at=modified_at,
                    topic_cluster=topic.key,
                    extracted_text=gc.extracted_text,
                )
            )
            used_filenames.add(filename)

    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-files", type=int, default=350)
    parser.add_argument("--weeks", type=int, default=10, help="weeks of access log history to simulate")
    parser.add_argument("--corpus-dir", type=Path, default=REPO_ROOT / "data" / "files_corpus")
    parser.add_argument("--db-path", type=Path, default=REPO_ROOT / "data" / "db.sqlite")
    parser.add_argument(
        "--no-llm", action="store_true",
        help="force the template content generator even if GEMINI_API_KEY is set",
    )
    args = parser.parse_args()

    from app.llm_client import get_client

    use_llm = (not args.no_llm) and get_client().is_available
    print(f"[generate_synthetic_data] content backend: {'Gemini' if use_llm else 'template (no API key)'}")

    if args.corpus_dir.exists():
        shutil.rmtree(args.corpus_dir)
    args.corpus_dir.mkdir(parents=True)
    if args.db_path.exists():
        args.db_path.unlink()

    now = datetime.now()

    print(f"[generate_synthetic_data] generating {args.num_files} files across {len(TOPICS)} topics (seed={args.seed})...")
    file_records = build_file_plan(args.num_files, args.seed, args.corpus_dir, now, use_llm)

    engine = create_engine(f"sqlite:///{args.db_path}")
    SQLModel.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:
        for rec in file_records:
            session.add(rec)
        session.commit()

        users: list[UserRecord] = []
        for persona in PERSONAS:
            user = UserRecord(name=persona.name, persona_key=persona.key)
            session.add(user)
            users.append(user)
        session.commit()

        user_personas = list(zip(users, PERSONAS))
        print(f"[generate_synthetic_data] simulating {args.weeks} weeks of access log for {len(users)} personas...")
        result = simulate_access_log(file_records, user_personas, args.weeks, args.seed)

        for event in result.events:
            session.add(event)
        session.commit()

    # Summary
    print("\n[generate_synthetic_data] done.")
    print(f"  files:        {len(file_records)}")
    by_type: dict[str, int] = {}
    for r in file_records:
        by_type[r.file_type] = by_type.get(r.file_type, 0) + 1
    print(f"  by file type: {dict(sorted(by_type.items()))}")
    by_topic: dict[str, int] = {}
    for r in file_records:
        by_topic[r.topic_cluster] = by_topic.get(r.topic_cluster, 0) + 1
    print(f"  by topic:     {dict(sorted(by_topic.items()))}")
    print(f"  users:        {[u.name for u in users]}")
    print(f"  access events:{len(result.events)}")
    for user, persona in user_personas:
        n = sum(1 for e in result.events if e.user_id == user.id)
        recurring = result.recurring_files_by_user.get(user.id, {})
        print(f"    {user.name} ({persona.key}): {n} events, recurring weekday->files: {recurring}")
    print(f"\n  corpus dir: {args.corpus_dir}")
    print(f"  db path:    {args.db_path}")


if __name__ == "__main__":
    main()
