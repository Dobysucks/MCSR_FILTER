from __future__ import annotations

import os
import sqlite3
import tempfile
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Iterable

MIN_SEED, MAX_SEED = -(1 << 63), (1 << 63) - 1


def parse_seed(value: str) -> str:
    text = value.strip()
    number = int(text, 10)
    if not MIN_SEED <= number <= MAX_SEED:
        raise ValueError("seed is outside the signed 64-bit Java range")
    return str(number)


class SeedCache:
    def __init__(self, database: Path, text_file: Path, minecraft_version: str, filter_version: str, pool: str = "overworld"):
        self.database = database
        self.text_file = text_file
        self.minecraft_version = minecraft_version
        self.filter_version = filter_version
        if pool not in {"overworld", "nether"}:
            raise ValueError("pool must be overworld or nether")
        self.pool = pool
        self.table = f"{pool}_seeds"
        self._lock = Lock()
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            f"""CREATE TABLE IF NOT EXISTS {self.table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seed TEXT NOT NULL UNIQUE,
                minecraft_version TEXT NOT NULL,
                filter_version TEXT NOT NULL,
                labels TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )"""
        )
        columns = {row[1] for row in self.connection.execute(f"PRAGMA table_info({self.table})")}
        if "labels" not in columns:
            self.connection.execute(f"ALTER TABLE {self.table} ADD COLUMN labels TEXT NOT NULL DEFAULT '[]'")
        self.connection.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.pool}_seed ON {self.table}(seed)")
        self.connection.commit()
        self.recover()

    def __enter__(self) -> "SeedCache":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def count(self) -> int:
        return int(self.connection.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()[0])

    def contains(self, seed: str) -> bool:
        return self.connection.execute(f"SELECT 1 FROM {self.table} WHERE seed = ?", (parse_seed(seed),)).fetchone() is not None

    def insert(self, seed: str, labels: Iterable[str] = ()) -> bool:
        seed = parse_seed(seed)
        labels_json = json.dumps(list(dict.fromkeys(labels)), ensure_ascii=False)
        with self._lock:
            cursor = self.connection.execute(
                f"INSERT OR IGNORE INTO {self.table}(seed, minecraft_version, filter_version, labels, created_at) VALUES (?, ?, ?, ?, ?)",
                (seed, self.minecraft_version, self.filter_version, labels_json, datetime.now(timezone.utc).isoformat()),
            )
            self.connection.commit()
            return cursor.rowcount == 1

    def insert_many(self, seeds: Iterable[str]) -> int:
        inserted = 0
        with self._lock:
            for seed in seeds:
                try:
                    seed = parse_seed(seed)
                except (TypeError, ValueError):
                    continue
                cursor = self.connection.execute(
                    f"INSERT OR IGNORE INTO {self.table}(seed, minecraft_version, filter_version, labels, created_at) VALUES (?, ?, ?, ?, ?)",
                    (seed, self.minecraft_version, self.filter_version, "[]", datetime.now(timezone.utc).isoformat()),
                )
                inserted += cursor.rowcount
            self.connection.commit()
        return inserted

    def seeds(self) -> list[str]:
        return [row[0] for row in self.connection.execute(f"SELECT seed FROM {self.table} ORDER BY id")]

    def entries(self) -> list[tuple[str, list[str]]]:
        entries = []
        for seed, raw_labels in self.connection.execute(f"SELECT seed, labels FROM {self.table} ORDER BY id"):
            try:
                labels = json.loads(raw_labels)
            except (TypeError, ValueError):
                labels = []
            entries.append((seed, labels if isinstance(labels, list) else []))
        return entries

    def recover(self) -> None:
        imported: list[str] = []
        if self.count() == 0 and self.text_file.exists():
            for line in self.text_file.read_text(encoding="utf-8").splitlines():
                try:
                    match = re.match(r"^\s*SEED:\s*(-?\d+)", line)
                    imported.append(parse_seed(match.group(1) if match else line))
                except (TypeError, ValueError):
                    continue
        if imported:
            self.insert_many(imported)
        self.export()

    def export(self, generated_count: int | None = None) -> None:
        self.text_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=self.text_file.name + ".", dir=self.text_file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(f"Minecraft Java: {self.minecraft_version}\n")
                handle.write(f"Filter: {self.filter_version}\n")
                handle.write(f"Generated count: {self.count() if generated_count is None else generated_count}\n\n")
                for seed, labels in self.entries():
                    suffix = f" ({', '.join(labels)})" if labels else ""
                    handle.write(f"SEED: {seed}{suffix}\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.text_file)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
