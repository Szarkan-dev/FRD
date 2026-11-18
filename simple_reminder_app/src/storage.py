"""
Data Access Object (DAO) & Persistence Layer for Simple Reminder List Application.

Implements robust file operations for JSON and CSV storage formats, featuring zero-dependency
error recovery for missing or corrupted files, schema validation, and automatic backups.
"""

import csv
import json
import os
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from src.models import Reminder, Priority, Category, ReminderStatus


class StorageError(Exception):
    """Custom exception raised during storage read/write operations."""
    pass


class ReminderDAO:
    """
    Data Access Object encapsulating CRUD operations and file persistence for Reminders.
    Supports both JSON and CSV backing stores with schema verification and fallback recovery.
    """

    CSV_HEADERS = [
        "id", "title", "category", "due_date", "priority",
        "description", "status", "created_at", "completed_at"
    ]

    def __init__(self, file_path: str = "data/reminders.json"):
        self.file_path = Path(file_path)
        self.format = self.file_path.suffix.lower().strip(".")
        if self.format not in ("json", "csv"):
            raise ValueError(f"Unsupported storage format: '{self.format}'. Use 'json' or 'csv'.")
        self._ensure_storage_exists()

    def _ensure_storage_exists(self) -> None:
        """Create storage directory and seed file if missing or corrupted."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._initialize_empty_storage()
        else:
            # Verify file integrity
            try:
                self.load_all()
            except StorageError:
                self._backup_corrupted_file()
                self._initialize_empty_storage()

    def _initialize_empty_storage(self) -> None:
        """Create a fresh, empty storage file with default structure."""
        if self.format == "json":
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump({"reminders": [], "last_id": 0, "updated_at": datetime.now().isoformat()}, f, indent=2)
        elif self.format == "csv":
            with open(self.file_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(self.CSV_HEADERS)

    def _backup_corrupted_file(self) -> None:
        """Rename corrupted storage file with timestamp suffix to prevent data loss."""
        if self.file_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            corrupt_path = self.file_path.with_name(f"{self.file_path.stem}_corrupt_{timestamp}{self.file_path.suffix}")
            try:
                shutil.copy(self.file_path, corrupt_path)
            except Exception:
                pass

    def load_all(self) -> List[Reminder]:
        """Load and deserialize all reminder records from disk."""
        if not self.file_path.exists():
            self._initialize_empty_storage()
            return []

        reminders: List[Reminder] = []
        if self.format == "json":
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                items = data.get("reminders", []) if isinstance(data, dict) else data
                for item in items:
                    if isinstance(item, dict):
                        reminders.append(Reminder.from_dict(item))
            except (json.JSONDecodeError, OSError) as e:
                raise StorageError(f"Failed to parse JSON storage file: {e}")
        elif self.format == "csv":
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Defensive conversion of row values
                        row_dict = {
                            "id": int(row.get("id", 0)),
                            "title": row.get("title", ""),
                            "category": row.get("category", Category.OTHER.value),
                            "due_date": row.get("due_date", ""),
                            "priority": row.get("priority", Priority.MEDIUM.value),
                            "description": row.get("description", ""),
                            "status": row.get("status", ReminderStatus.PENDING.value),
                            "created_at": row.get("created_at", ""),
                            "completed_at": row.get("completed_at") or None
                        }
                        reminders.append(Reminder.from_dict(row_dict))
            except (csv.Error, ValueError, OSError) as e:
                raise StorageError(f"Failed to parse CSV storage file: {e}")

        return sorted(reminders, key=lambda r: r.id)

    def save_all(self, reminders: List[Reminder]) -> None:
        """Serialize and save all reminder records to disk."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        max_id = max((r.id for r in reminders), default=0)

        if self.format == "json":
            payload = {
                "reminders": [r.to_dict() for r in reminders],
                "last_id": max_id,
                "updated_at": datetime.now().isoformat()
            }
            temp_path = self.file_path.with_suffix(".tmp")
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
                temp_path.replace(self.file_path)
            except OSError as e:
                if temp_path.exists():
                    temp_path.unlink()
                raise StorageError(f"Atomic JSON write failed: {e}")
        elif self.format == "csv":
            temp_path = self.file_path.with_suffix(".tmp")
            try:
                with open(temp_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=self.CSV_HEADERS)
                    writer.writeheader()
                    for r in reminders:
                        d = r.to_dict()
                        if d["completed_at"] is None:
                            d["completed_at"] = ""
                        writer.writerow(d)
                temp_path.replace(self.file_path)
            except OSError as e:
                if temp_path.exists():
                    temp_path.unlink()
                raise StorageError(f"Atomic CSV write failed: {e}")

    def add(self, reminder: Reminder) -> Reminder:
        """Add a new reminder, automatically assigning a unique ID if 0."""
        reminders = self.load_all()
        if reminder.id <= 0:
            next_id = max((r.id for r in reminders), default=0) + 1
            reminder.id = next_id
        reminders.append(reminder)
        self.save_all(reminders)
        return reminder

    def get_by_id(self, reminder_id: int) -> Optional[Reminder]:
        """Fetch a single reminder by ID."""
        reminders = self.load_all()
        for r in reminders:
            if r.id == reminder_id:
                return r
        return None

    def update(self, reminder: Reminder) -> bool:
        """Update an existing reminder record."""
        reminders = self.load_all()
        found = False
        for idx, r in enumerate(reminders):
            if r.id == reminder.id:
                reminders[idx] = reminder
                found = True
                break
        if found:
            self.save_all(reminders)
        return found

    def delete(self, reminder_id: int) -> bool:
        """Delete a reminder record by ID."""
        reminders = self.load_all()
        initial_len = len(reminders)
        reminders = [r for r in reminders if r.id != reminder_id]
        if len(reminders) < initial_len:
            self.save_all(reminders)
            return True
        return False

    def create_backup(self, backup_dir: str = "data/backups") -> Path:
        """Generate a timestamped backup copy of current storage."""
        b_path = Path(backup_dir)
        b_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = b_path / f"reminders_backup_{timestamp}.{self.format}"
        shutil.copy(self.file_path, backup_file)
        return backup_file
