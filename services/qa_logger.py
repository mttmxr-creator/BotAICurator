"""
QA Logger service for recording successful question-answer interactions.
Provides dual-format logging (JSONL + human-readable) with automatic file rotation.
"""

import os
import json
import logging
import threading
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class QAEntry:
    """Data structure for a Q&A log entry."""
    timestamp: str
    question: str
    answer: str
    context: str
    user_id: int
    chat_id: int
    username: str
    session_id: Optional[str] = None
    processing_time_ms: Optional[int] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

class QALogger:
    """
    Logger for successful question-answer interactions.

    Features:
    - Dual format output (JSONL for processing, TXT for human reading)
    - Automatic file rotation at 10MB
    - Thread-safe operations
    - Russian text support (UTF-8)
    - Automatic directory creation
    """

    def __init__(self, logs_dir: str = "logs", max_file_size: int = 10 * 1024 * 1024):
        """
        Initialize QA Logger.

        Args:
            logs_dir: Directory for log files (created if doesn't exist)
            max_file_size: Maximum file size before rotation (default: 10MB)
        """
        self.logs_dir = Path(logs_dir)
        self.max_file_size = max_file_size
        self._lock = threading.Lock()

        # File paths
        self.jsonl_file = self.logs_dir / "qa_log.jsonl"
        self.readable_file = self.logs_dir / "qa_log_readable.txt"

        # Ensure logs directory exists
        self._ensure_logs_directory()

        logger.info(f"📝 QA Logger initialized")
        logger.info(f"   📁 Logs directory: {self.logs_dir}")
        logger.info(f"   📊 Max file size: {self.max_file_size / (1024*1024):.1f} MB")

    def _ensure_logs_directory(self):
        """Create logs directory if it doesn't exist."""
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"✅ Logs directory ensured: {self.logs_dir}")
        except Exception as e:
            logger.error(f"❌ Failed to create logs directory {self.logs_dir}: {e}")
            raise

    def _should_rotate_files(self) -> bool:
        """Check if files need rotation based on size."""
        try:
            # Check JSONL file size (primary trigger)
            if self.jsonl_file.exists():
                size = self.jsonl_file.stat().st_size
                return size >= self.max_file_size
            return False
        except Exception as e:
            logger.warning(f"⚠️ Error checking file size for rotation: {e}")
            return False

    def _rotate_files(self):
        """Rotate both JSONL and readable files when size limit is reached."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Rotate JSONL file
            if self.jsonl_file.exists():
                rotated_jsonl = self.logs_dir / f"qa_log.jsonl.{timestamp}"
                self.jsonl_file.rename(rotated_jsonl)
                logger.info(f"🔄 Rotated JSONL file to: {rotated_jsonl.name}")

            # Rotate readable file
            if self.readable_file.exists():
                rotated_readable = self.logs_dir / f"qa_log_readable.txt.{timestamp}"
                self.readable_file.rename(rotated_readable)
                logger.info(f"🔄 Rotated readable file to: {rotated_readable.name}")

            # Clean up old rotated files (keep last 10)
            self._cleanup_old_rotated_files()

        except Exception as e:
            logger.error(f"❌ Failed to rotate log files: {e}")

    def _cleanup_old_rotated_files(self):
        """Remove old rotated files, keeping only the last 10."""
        try:
            # Clean JSONL rotated files
            jsonl_pattern = "qa_log.jsonl.*"
            jsonl_files = sorted(self.logs_dir.glob(jsonl_pattern))
            if len(jsonl_files) > 10:
                for old_file in jsonl_files[:-10]:
                    try:
                        old_file.unlink()
                        logger.debug(f"🗑️ Removed old JSONL file: {old_file.name}")
                    except Exception:
                        pass

            # Clean readable rotated files
            readable_pattern = "qa_log_readable.txt.*"
            readable_files = sorted(self.logs_dir.glob(readable_pattern))
            if len(readable_files) > 10:
                for old_file in readable_files[:-10]:
                    try:
                        old_file.unlink()
                        logger.debug(f"🗑️ Removed old readable file: {old_file.name}")
                    except Exception:
                        pass

        except Exception as e:
            logger.warning(f"⚠️ Failed to cleanup old rotated files: {e}")

    def _write_jsonl_entry(self, qa_entry: QAEntry):
        """Write entry to JSONL file."""
        try:
            entry_dict = asdict(qa_entry)
            json_line = json.dumps(entry_dict, ensure_ascii=False, separators=(',', ':'))

            with open(self.jsonl_file, 'a', encoding='utf-8') as f:
                f.write(json_line + '\n')

        except Exception as e:
            logger.error(f"❌ Failed to write JSONL entry: {e}")
            raise

    def _write_readable_entry(self, qa_entry: QAEntry):
        """Write entry to human-readable file."""
        try:
            # Format timestamp for display
            try:
                timestamp_obj = datetime.fromisoformat(qa_entry.timestamp.replace('Z', '+00:00'))
                formatted_time = timestamp_obj.strftime("%Y-%m-%d %H:%M:%S")
            except:
                formatted_time = qa_entry.timestamp

            # Truncate context to first 200 characters
            context_preview = qa_entry.context[:200] if qa_entry.context else "Нет контекста"
            if len(qa_entry.context) > 200:
                context_preview += "..."

            # Format the readable entry
            readable_entry = f"""===== [{formatted_time}] =====
Пользователь: {qa_entry.username} (ID: {qa_entry.user_id})
Чат: {qa_entry.chat_id}
Вопрос: {qa_entry.question}
Контекст из базы: {context_preview}
Ответ: {qa_entry.answer}
========================

"""

            with open(self.readable_file, 'a', encoding='utf-8') as f:
                f.write(readable_entry)

        except Exception as e:
            logger.error(f"❌ Failed to write readable entry: {e}")
            raise

    def log_qa(self, question: str, answer: str, context: str,
               timestamp: Optional[str] = None, user_info: Optional[Dict[str, Any]] = None,
               session_id: Optional[str] = None, processing_time_ms: Optional[int] = None,
               **metadata):
        """
        Log a successful question-answer interaction.

        Args:
            question: User's question
            answer: AI's response
            context: Context from knowledge base
            timestamp: ISO timestamp (auto-generated if None)
            user_info: Dictionary with user_id, chat_id, username
            session_id: Optional session identifier
            processing_time_ms: Time taken to process the request
            **metadata: Additional metadata to include
        """

        # Input validation
        if not question or not answer:
            logger.warning("⚠️ Skipping QA log: question or answer is empty")
            return

        # Prepare user information
        if user_info is None:
            user_info = {}

        user_id = user_info.get('user_id', 0)
        chat_id = user_info.get('chat_id', 0)
        username = user_info.get('username', 'Unknown')

        # Generate timestamp if not provided
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        # Create QA entry
        qa_entry = QAEntry(
            timestamp=timestamp,
            question=question,
            answer=answer,
            context=context or "",
            user_id=user_id,
            chat_id=chat_id,
            username=username,
            session_id=session_id,
            processing_time_ms=processing_time_ms,
            metadata=metadata
        )

        # Thread-safe logging
        with self._lock:
            try:
                # Check if files need rotation
                if self._should_rotate_files():
                    logger.info("📂 File size limit reached, rotating log files...")
                    self._rotate_files()

                # Write to both formats
                self._write_jsonl_entry(qa_entry)
                self._write_readable_entry(qa_entry)

                logger.debug(f"✅ QA logged for user {username} ({user_id})")

            except Exception as e:
                logger.error(f"❌ Failed to log QA interaction: {e}")
                # Don't re-raise to avoid breaking the main application flow

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the QA logs."""
        stats = {
            "logs_directory": str(self.logs_dir),
            "max_file_size_mb": self.max_file_size / (1024 * 1024),
            "files": {}
        }

        try:
            # JSONL file stats
            if self.jsonl_file.exists():
                jsonl_stat = self.jsonl_file.stat()
                stats["files"]["jsonl"] = {
                    "exists": True,
                    "size_bytes": jsonl_stat.st_size,
                    "size_mb": jsonl_stat.st_size / (1024 * 1024),
                    "created": datetime.fromtimestamp(jsonl_stat.st_ctime).isoformat(),
                    "modified": datetime.fromtimestamp(jsonl_stat.st_mtime).isoformat()
                }
            else:
                stats["files"]["jsonl"] = {"exists": False}

            # Readable file stats
            if self.readable_file.exists():
                readable_stat = self.readable_file.stat()
                stats["files"]["readable"] = {
                    "exists": True,
                    "size_bytes": readable_stat.st_size,
                    "size_mb": readable_stat.st_size / (1024 * 1024),
                    "created": datetime.fromtimestamp(readable_stat.st_ctime).isoformat(),
                    "modified": datetime.fromtimestamp(readable_stat.st_mtime).isoformat()
                }
            else:
                stats["files"]["readable"] = {"exists": False}

            # Count rotated files
            jsonl_rotated = len(list(self.logs_dir.glob("qa_log.jsonl.*")))
            readable_rotated = len(list(self.logs_dir.glob("qa_log_readable.txt.*")))

            stats["rotated_files"] = {
                "jsonl_count": jsonl_rotated,
                "readable_count": readable_rotated
            }

        except Exception as e:
            logger.error(f"❌ Failed to get QA logger stats: {e}")
            stats["error"] = str(e)

        return stats

    def count_entries(self) -> int:
        """Count total entries in the current JSONL file."""
        try:
            if not self.jsonl_file.exists():
                return 0

            with open(self.jsonl_file, 'r', encoding='utf-8') as f:
                return sum(1 for line in f if line.strip())

        except Exception as e:
            logger.error(f"❌ Failed to count QA entries: {e}")
            return -1

    def export_recent_entries(self, limit: int = 100) -> list:
        """Export recent QA entries for analysis."""
        entries = []

        try:
            if not self.jsonl_file.exists():
                return entries

            with open(self.jsonl_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Get last N lines
            recent_lines = lines[-limit:] if len(lines) > limit else lines

            for line in recent_lines:
                if line.strip():
                    try:
                        entry = json.loads(line.strip())
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            logger.error(f"❌ Failed to export recent QA entries: {e}")

        return entries


# Global instance management
_qa_logger = None

def get_qa_logger() -> QALogger:
    """Get the global QA Logger instance."""
    global _qa_logger
    if _qa_logger is None:
        _qa_logger = QALogger()
    return _qa_logger

def log_qa_interaction(question: str, answer: str, context: str,
                      user_info: Dict[str, Any], session_id: Optional[str] = None,
                      processing_time_ms: Optional[int] = None, **metadata):
    """
    Convenience function to log QA interaction.

    Args:
        question: User's question
        answer: AI's response
        context: Context from knowledge base
        user_info: Dict with user_id, chat_id, username
        session_id: Optional session identifier
        processing_time_ms: Processing time in milliseconds
        **metadata: Additional metadata
    """
    qa_logger = get_qa_logger()
    qa_logger.log_qa(
        question=question,
        answer=answer,
        context=context,
        user_info=user_info,
        session_id=session_id,
        processing_time_ms=processing_time_ms,
        **metadata
    )

def get_qa_stats() -> Dict[str, Any]:
    """Get QA logging statistics."""
    return get_qa_logger().get_stats()