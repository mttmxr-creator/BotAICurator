"""
Comprehensive metrics service for tracking processing times, correction statistics,
and structured logging across the bot moderation system.
"""

import logging
import json
import uuid
import time
import sqlite3
import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict, field
from contextlib import asynccontextmanager, contextmanager
from enum import Enum
from pathlib import Path
import threading
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

class ProcessingStage(Enum):
    """Enumeration of processing stages for timing."""
    QUERY_RECEIVED = "query_received"
    AI_PROCESSING = "ai_processing"
    AI_RESPONSE = "ai_response"
    MODERATION_QUEUE = "moderation_queue"
    ADMIN_REVIEW = "admin_review"
    CORRECTION_PROCESSING = "correction_processing"
    CORRECTION_AI = "correction_ai"
    FINAL_RESPONSE = "final_response"
    USER_DELIVERY = "user_delivery"

class CorrectionType(Enum):
    """Types of corrections made by admins."""
    TEXT_CORRECTION = "text_correction"
    VOICE_CORRECTION = "voice_correction"
    CONTENT_MODIFICATION = "content_modification"
    STYLE_IMPROVEMENT = "style_improvement"
    FACTUAL_CORRECTION = "factual_correction"
    REJECTION = "rejection"

class FilteringReason(Enum):
    """Reasons for message filtering/rejection."""
    LENGTH_CHECK = "length_check"
    WORK_VALIDATION = "work_validation"
    RELEVANCE_CHECK = "relevance_check"
    NONE = "none"  # Message passed all filters

class LogLevel(Enum):
    """Structured log levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    METRIC = "metric"

@dataclass
class ProcessingMetric:
    """Individual processing time metric."""
    metric_id: str
    session_id: str
    user_id: int
    chat_id: int
    stage: ProcessingStage
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = None
    success: bool = True
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def complete(self, success: bool = True, error_message: Optional[str] = None, **metadata):
        """Mark the metric as complete."""
        self.end_time = datetime.now()
        self.duration_ms = int((self.end_time - self.start_time).total_seconds() * 1000)
        self.success = success
        self.error_message = error_message
        self.metadata.update(metadata)

@dataclass
class CorrectionMetric:
    """Correction-specific metric."""
    correction_id: str
    session_id: str
    admin_user_id: int
    message_id: str
    correction_type: CorrectionType
    original_length: int
    corrected_length: int
    processing_time_ms: int
    voice_transcription_time_ms: Optional[int] = None
    ai_correction_time_ms: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)
    admin_satisfaction: Optional[int] = None  # 1-5 rating
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class FilteringMetric:
    """Message filtering metric."""
    filtering_id: str
    session_id: str
    user_id: int
    chat_id: int
    message_length: int
    filtering_reason: FilteringReason
    stage_failed: Optional[str] = None  # Specific stage that failed
    processing_time_ms: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    message_preview: str = ""  # First 100 chars for analysis
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SystemMetric:
    """System-wide performance metric."""
    timestamp: datetime
    metric_type: str
    value: Union[int, float, str]
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

class StructuredLogger:
    """JSON-based structured logger for metrics and events."""

    def __init__(self, log_file: str = "metrics.jsonl", max_file_size: int = 100 * 1024 * 1024):
        self.log_file = log_file
        self.max_file_size = max_file_size
        self._lock = threading.Lock()

    def log(self, level: LogLevel, event_type: str, message: str,
            session_id: Optional[str] = None, user_id: Optional[int] = None,
            **kwargs):
        """Log structured event."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level.value,
            "event_type": event_type,
            "message": message,
            "session_id": session_id,
            "user_id": user_id,
            **kwargs
        }

        with self._lock:
            try:
                # Rotate log file if too large
                if os.path.exists(self.log_file) and os.path.getsize(self.log_file) > self.max_file_size:
                    self._rotate_log_file()

                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

            except Exception as e:
                logger.error(f"Failed to write structured log: {e}")

    def _rotate_log_file(self):
        """Rotate log file when it gets too large."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            rotated_file = f"{self.log_file}.{timestamp}"
            os.rename(self.log_file, rotated_file)

            # Keep only last 10 rotated files
            log_dir = os.path.dirname(self.log_file) or '.'
            base_name = os.path.basename(self.log_file)
            rotated_files = sorted([
                f for f in os.listdir(log_dir)
                if f.startswith(f"{base_name}.")
            ])

            if len(rotated_files) > 10:
                for old_file in rotated_files[:-10]:
                    try:
                        os.remove(os.path.join(log_dir, old_file))
                    except Exception:
                        pass

        except Exception as e:
            logger.warning(f"Failed to rotate log file: {e}")

class ProcessingTimer:
    """Context manager for timing processing stages."""

    def __init__(self, metrics_service: 'MetricsService', session_id: str,
                 user_id: int, chat_id: int, stage: ProcessingStage):
        self.metrics_service = metrics_service
        self.session_id = session_id
        self.user_id = user_id
        self.chat_id = chat_id
        self.stage = stage
        self.metric: Optional[ProcessingMetric] = None

    def __enter__(self):
        self.metric = self.metrics_service.start_timing(
            self.session_id, self.user_id, self.chat_id, self.stage
        )
        return self.metric

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.metric:
            success = exc_type is None
            error_message = str(exc_val) if exc_val else None
            self.metrics_service.complete_timing(
                self.metric.metric_id, success=success, error_message=error_message
            )

class MetricsStorage:
    """Storage layer for metrics data."""

    def __init__(self, db_file: str = "metrics.db"):
        self.db_file = db_file
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database for metrics storage."""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            # Processing metrics table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS processing_metrics (
                    metric_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    duration_ms INTEGER,
                    success BOOLEAN,
                    error_message TEXT,
                    metadata TEXT
                )
            ''')

            # Correction metrics table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS correction_metrics (
                    correction_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    admin_user_id INTEGER NOT NULL,
                    message_id TEXT NOT NULL,
                    correction_type TEXT NOT NULL,
                    original_length INTEGER,
                    corrected_length INTEGER,
                    processing_time_ms INTEGER,
                    voice_transcription_time_ms INTEGER,
                    ai_correction_time_ms INTEGER,
                    timestamp TEXT NOT NULL,
                    admin_satisfaction INTEGER,
                    retry_count INTEGER,
                    metadata TEXT
                )
            ''')

            # System metrics table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    metric_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    tags TEXT,
                    metadata TEXT
                )
            ''')

            # Filtering metrics table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS filtering_metrics (
                    filtering_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_length INTEGER NOT NULL,
                    filtering_reason TEXT NOT NULL,
                    stage_failed TEXT,
                    processing_time_ms INTEGER,
                    timestamp TEXT NOT NULL,
                    message_preview TEXT,
                    metadata TEXT
                )
            ''')

            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_processing_session ON processing_metrics(session_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_processing_stage ON processing_metrics(stage)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_processing_time ON processing_metrics(start_time)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_correction_admin ON correction_metrics(admin_user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_correction_type ON correction_metrics(correction_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_system_type ON system_metrics(metric_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_filtering_reason ON filtering_metrics(filtering_reason)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_filtering_timestamp ON filtering_metrics(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_filtering_user ON filtering_metrics(user_id)')

            conn.commit()
            conn.close()
            logger.info(f"📊 Metrics database initialized: {self.db_file}")

        except Exception as e:
            logger.error(f"❌ Failed to initialize metrics database: {e}")

    def save_processing_metric(self, metric: ProcessingMetric):
        """Save processing metric to database."""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO processing_metrics
                (metric_id, session_id, user_id, chat_id, stage, start_time, end_time,
                 duration_ms, success, error_message, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                metric.metric_id,
                metric.session_id,
                metric.user_id,
                metric.chat_id,
                metric.stage.value,
                metric.start_time.isoformat(),
                metric.end_time.isoformat() if metric.end_time else None,
                metric.duration_ms,
                metric.success,
                metric.error_message,
                json.dumps(metric.metadata)
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"❌ Failed to save processing metric: {e}")

    def save_correction_metric(self, metric: CorrectionMetric):
        """Save correction metric to database."""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO correction_metrics
                (correction_id, session_id, admin_user_id, message_id, correction_type,
                 original_length, corrected_length, processing_time_ms, voice_transcription_time_ms,
                 ai_correction_time_ms, timestamp, admin_satisfaction, retry_count, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                metric.correction_id,
                metric.session_id,
                metric.admin_user_id,
                metric.message_id,
                metric.correction_type.value,
                metric.original_length,
                metric.corrected_length,
                metric.processing_time_ms,
                metric.voice_transcription_time_ms,
                metric.ai_correction_time_ms,
                metric.timestamp.isoformat(),
                metric.admin_satisfaction,
                metric.retry_count,
                json.dumps(metric.metadata)
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"❌ Failed to save correction metric: {e}")

    def save_system_metric(self, metric: SystemMetric):
        """Save system metric to database."""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO system_metrics (timestamp, metric_type, value, tags, metadata)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                metric.timestamp.isoformat(),
                metric.metric_type,
                str(metric.value),
                json.dumps(metric.tags),
                json.dumps(metric.metadata)
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"❌ Failed to save system metric: {e}")

    def save_filtering_metric(self, metric: FilteringMetric):
        """Save filtering metric to database."""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO filtering_metrics
                (filtering_id, session_id, user_id, chat_id, message_length, filtering_reason,
                 stage_failed, processing_time_ms, timestamp, message_preview, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                metric.filtering_id,
                metric.session_id,
                metric.user_id,
                metric.chat_id,
                metric.message_length,
                metric.filtering_reason.value,
                metric.stage_failed,
                metric.processing_time_ms,
                metric.timestamp.isoformat(),
                metric.message_preview,
                json.dumps(metric.metadata)
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"❌ Failed to save filtering metric: {e}")

    def get_processing_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get processing statistics for the last N hours."""
        try:
            since = datetime.now() - timedelta(hours=hours)
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Average processing times by stage
            cursor.execute('''
                SELECT stage,
                       AVG(duration_ms) as avg_duration,
                       MIN(duration_ms) as min_duration,
                       MAX(duration_ms) as max_duration,
                       COUNT(*) as total_count,
                       SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count
                FROM processing_metrics
                WHERE start_time >= ? AND duration_ms IS NOT NULL
                GROUP BY stage
            ''', (since.isoformat(),))

            stage_stats = {}
            for row in cursor.fetchall():
                stage_stats[row['stage']] = {
                    'avg_duration_ms': round(row['avg_duration'], 2),
                    'min_duration_ms': row['min_duration'],
                    'max_duration_ms': row['max_duration'],
                    'total_count': row['total_count'],
                    'success_rate': round(row['success_count'] / row['total_count'] * 100, 2)
                }

            conn.close()
            return stage_stats

        except Exception as e:
            logger.error(f"❌ Failed to get processing stats: {e}")
            return {}

    def get_correction_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get correction statistics for the last N hours."""
        try:
            since = datetime.now() - timedelta(hours=hours)
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Correction statistics
            cursor.execute('''
                SELECT correction_type,
                       COUNT(*) as total_count,
                       AVG(processing_time_ms) as avg_processing_time,
                       AVG(CASE WHEN admin_satisfaction IS NOT NULL THEN admin_satisfaction END) as avg_satisfaction,
                       AVG(corrected_length - original_length) as avg_length_change
                FROM correction_metrics
                WHERE timestamp >= ?
                GROUP BY correction_type
            ''', (since.isoformat(),))

            correction_stats = {}
            for row in cursor.fetchall():
                correction_stats[row['correction_type']] = {
                    'total_count': row['total_count'],
                    'avg_processing_time_ms': round(row['avg_processing_time'], 2),
                    'avg_satisfaction': round(row['avg_satisfaction'], 2) if row['avg_satisfaction'] else None,
                    'avg_length_change': round(row['avg_length_change'], 2)
                }

            # Admin performance
            cursor.execute('''
                SELECT admin_user_id,
                       COUNT(*) as total_corrections,
                       AVG(processing_time_ms) as avg_processing_time,
                       AVG(CASE WHEN admin_satisfaction IS NOT NULL THEN admin_satisfaction END) as avg_satisfaction
                FROM correction_metrics
                WHERE timestamp >= ?
                GROUP BY admin_user_id
            ''', (since.isoformat(),))

            admin_stats = {}
            for row in cursor.fetchall():
                admin_stats[str(row['admin_user_id'])] = {
                    'total_corrections': row['total_corrections'],
                    'avg_processing_time_ms': round(row['avg_processing_time'], 2),
                    'avg_satisfaction': round(row['avg_satisfaction'], 2) if row['avg_satisfaction'] else None
                }

            conn.close()
            return {
                'by_type': correction_stats,
                'by_admin': admin_stats
            }

        except Exception as e:
            logger.error(f"❌ Failed to get correction stats: {e}")
            return {}

    def get_filtering_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get filtering statistics for the last N hours."""
        try:
            since = datetime.now() - timedelta(hours=hours)
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Filtering statistics by reason
            cursor.execute('''
                SELECT filtering_reason,
                       COUNT(*) as total_count,
                       AVG(processing_time_ms) as avg_processing_time,
                       AVG(message_length) as avg_message_length,
                       COUNT(CASE WHEN filtering_reason != 'none' THEN 1 END) as rejected_count
                FROM filtering_metrics
                WHERE timestamp >= ?
                GROUP BY filtering_reason
            ''', (since.isoformat(),))

            filtering_stats = {}
            total_messages = 0
            total_rejected = 0

            for row in cursor.fetchall():
                reason = row['filtering_reason']
                count = row['total_count']
                total_messages += count

                if reason != 'none':
                    total_rejected += count

                filtering_stats[reason] = {
                    'total_count': count,
                    'avg_processing_time_ms': round(row['avg_processing_time'], 2) if row['avg_processing_time'] else 0,
                    'avg_message_length': round(row['avg_message_length'], 2) if row['avg_message_length'] else 0,
                }

            # Calculate overall filtering statistics
            pass_rate = ((total_messages - total_rejected) / total_messages * 100) if total_messages > 0 else 0
            rejection_rate = (total_rejected / total_messages * 100) if total_messages > 0 else 0

            # Message length distribution for rejected messages
            cursor.execute('''
                SELECT
                    CASE
                        WHEN message_length < 10 THEN 'very_short'
                        WHEN message_length < 50 THEN 'short'
                        WHEN message_length < 200 THEN 'medium'
                        ELSE 'long'
                    END as length_category,
                    COUNT(*) as count
                FROM filtering_metrics
                WHERE timestamp >= ? AND filtering_reason != 'none'
                GROUP BY length_category
            ''', (since.isoformat(),))

            length_distribution = {}
            for row in cursor.fetchall():
                length_distribution[row['length_category']] = row['count']

            conn.close()

            return {
                'by_reason': filtering_stats,
                'summary': {
                    'total_messages': total_messages,
                    'total_rejected': total_rejected,
                    'total_passed': total_messages - total_rejected,
                    'pass_rate': round(pass_rate, 2),
                    'rejection_rate': round(rejection_rate, 2)
                },
                'rejected_by_length': length_distribution
            }

        except Exception as e:
            logger.error(f"❌ Failed to get filtering stats: {e}")
            return {}

class MetricsService:
    """Main metrics service for tracking all system metrics."""

    def __init__(self, storage_file: str = "metrics.db", log_file: str = "metrics.jsonl"):
        self.storage = MetricsStorage(storage_file)
        self.logger = StructuredLogger(log_file)
        self.active_timers: Dict[str, ProcessingMetric] = {}
        self._lock = threading.Lock()

        # Start background metrics collection
        self._start_system_metrics_task()

        logger.info("📊 Metrics service initialized")

    def create_session(self, user_id: int, chat_id: int) -> str:
        """Create a new metrics session for tracking a complete user interaction."""
        session_id = str(uuid.uuid4())[:12]

        self.logger.log(
            LogLevel.INFO,
            "session_created",
            f"New metrics session created for user {user_id}",
            session_id=session_id,
            user_id=user_id,
            chat_id=chat_id
        )

        return session_id

    def start_timing(self, session_id: str, user_id: int, chat_id: int,
                     stage: ProcessingStage) -> ProcessingMetric:
        """Start timing a processing stage."""
        metric_id = str(uuid.uuid4())[:8]

        metric = ProcessingMetric(
            metric_id=metric_id,
            session_id=session_id,
            user_id=user_id,
            chat_id=chat_id,
            stage=stage,
            start_time=datetime.now()
        )

        with self._lock:
            self.active_timers[metric_id] = metric

        self.logger.log(
            LogLevel.METRIC,
            "timing_started",
            f"Started timing {stage.value}",
            session_id=session_id,
            user_id=user_id,
            metric_id=metric_id,
            stage=stage.value
        )

        return metric

    def complete_timing(self, metric_id: str, success: bool = True,
                       error_message: Optional[str] = None, **metadata):
        """Complete a timing metric."""
        with self._lock:
            metric = self.active_timers.pop(metric_id, None)

        if metric:
            metric.complete(success=success, error_message=error_message, **metadata)
            self.storage.save_processing_metric(metric)

            self.logger.log(
                LogLevel.METRIC,
                "timing_completed",
                f"Completed timing {metric.stage.value}",
                session_id=metric.session_id,
                user_id=metric.user_id,
                metric_id=metric_id,
                stage=metric.stage.value,
                duration_ms=metric.duration_ms,
                success=success,
                error_message=error_message
            )

    def timer(self, session_id: str, user_id: int, chat_id: int,
              stage: ProcessingStage) -> ProcessingTimer:
        """Get a context manager for timing a processing stage."""
        return ProcessingTimer(self, session_id, user_id, chat_id, stage)

    def record_correction(self, session_id: str, admin_user_id: int, message_id: str,
                         correction_type: CorrectionType, original_text: str,
                         corrected_text: str, processing_time_ms: int,
                         voice_transcription_time_ms: Optional[int] = None,
                         ai_correction_time_ms: Optional[int] = None,
                         admin_satisfaction: Optional[int] = None,
                         retry_count: int = 0, **metadata):
        """Record a correction metric."""
        correction_id = str(uuid.uuid4())[:8]

        correction_metric = CorrectionMetric(
            correction_id=correction_id,
            session_id=session_id,
            admin_user_id=admin_user_id,
            message_id=message_id,
            correction_type=correction_type,
            original_length=len(original_text),
            corrected_length=len(corrected_text),
            processing_time_ms=processing_time_ms,
            voice_transcription_time_ms=voice_transcription_time_ms,
            ai_correction_time_ms=ai_correction_time_ms,
            admin_satisfaction=admin_satisfaction,
            retry_count=retry_count,
            metadata=metadata
        )

        self.storage.save_correction_metric(correction_metric)

        self.logger.log(
            LogLevel.METRIC,
            "correction_recorded",
            f"Correction recorded: {correction_type.value}",
            session_id=session_id,
            admin_user_id=admin_user_id,
            correction_id=correction_id,
            correction_type=correction_type.value,
            original_length=len(original_text),
            corrected_length=len(corrected_text),
            processing_time_ms=processing_time_ms,
            length_change=len(corrected_text) - len(original_text)
        )

    def record_system_metric(self, metric_type: str, value: Union[int, float, str],
                            tags: Optional[Dict[str, str]] = None, **metadata):
        """Record a system-level metric."""
        system_metric = SystemMetric(
            timestamp=datetime.now(),
            metric_type=metric_type,
            value=value,
            tags=tags or {},
            metadata=metadata
        )

        self.storage.save_system_metric(system_metric)

        self.logger.log(
            LogLevel.METRIC,
            "system_metric",
            f"System metric recorded: {metric_type}",
            metric_type=metric_type,
            value=value,
            tags=tags
        )

    def record_filtered_message(self, session_id: str, user_id: int, chat_id: int,
                               message: str, reason: str, stage_failed: Optional[str] = None,
                               processing_time_ms: int = 0, **metadata):
        """Record a message filtering event."""
        filtering_id = str(uuid.uuid4())[:8]

        # Map stage_failed to FilteringReason
        if reason == "none" or not reason:
            filtering_reason = FilteringReason.NONE
        elif reason == "length_check":
            filtering_reason = FilteringReason.LENGTH_CHECK
        elif reason == "work_validation":
            filtering_reason = FilteringReason.WORK_VALIDATION
        elif reason == "relevance_check":
            filtering_reason = FilteringReason.RELEVANCE_CHECK
        else:
            # Default fallback
            filtering_reason = FilteringReason.NONE

        filtering_metric = FilteringMetric(
            filtering_id=filtering_id,
            session_id=session_id,
            user_id=user_id,
            chat_id=chat_id,
            message_length=len(message),
            filtering_reason=filtering_reason,
            stage_failed=stage_failed,
            processing_time_ms=processing_time_ms,
            message_preview=message[:100] if message else "",
            metadata=metadata
        )

        self.storage.save_filtering_metric(filtering_metric)

        self.logger.log(
            LogLevel.METRIC,
            "message_filtered",
            f"Message filtering recorded: {filtering_reason.value}",
            session_id=session_id,
            user_id=user_id,
            chat_id=chat_id,
            filtering_id=filtering_id,
            filtering_reason=filtering_reason.value,
            stage_failed=stage_failed,
            message_length=len(message),
            processing_time_ms=processing_time_ms
        )

    def get_dashboard_data(self, hours: int = 24) -> Dict[str, Any]:
        """Get comprehensive dashboard data for the last N hours."""
        processing_stats = self.storage.get_processing_stats(hours)
        correction_stats = self.storage.get_correction_stats(hours)
        filtering_stats = self.storage.get_filtering_stats(hours)

        # Calculate overall performance metrics
        total_processing_time = sum(
            stats['avg_duration_ms'] * stats['total_count']
            for stats in processing_stats.values()
        )
        total_requests = sum(stats['total_count'] for stats in processing_stats.values())
        avg_total_processing_time = total_processing_time / total_requests if total_requests > 0 else 0

        overall_success_rate = sum(
            stats['success_rate'] * stats['total_count']
            for stats in processing_stats.values()
        ) / sum(stats['total_count'] for stats in processing_stats.values()) if total_requests > 0 else 0

        return {
            'time_period_hours': hours,
            'generated_at': datetime.now().isoformat(),
            'overview': {
                'total_requests': total_requests,
                'avg_total_processing_time_ms': round(avg_total_processing_time, 2),
                'overall_success_rate': round(overall_success_rate, 2),
                'total_corrections': sum(
                    stats['total_count']
                    for stats in correction_stats.get('by_type', {}).values()
                ),
                'total_messages_filtered': filtering_stats.get('summary', {}).get('total_messages', 0),
                'filtering_pass_rate': filtering_stats.get('summary', {}).get('pass_rate', 0),
                'filtering_rejection_rate': filtering_stats.get('summary', {}).get('rejection_rate', 0)
            },
            'processing_by_stage': processing_stats,
            'corrections': correction_stats,
            'filtering': filtering_stats,
            'performance_alerts': self._generate_performance_alerts(processing_stats, correction_stats, filtering_stats)
        }

    def _generate_performance_alerts(self, processing_stats: Dict, correction_stats: Dict,
                                   filtering_stats: Dict) -> List[Dict]:
        """Generate performance alerts based on metrics."""
        alerts = []

        # Check for slow processing stages
        for stage, stats in processing_stats.items():
            if stats['avg_duration_ms'] > 10000:  # > 10 seconds
                alerts.append({
                    'type': 'slow_processing',
                    'severity': 'warning',
                    'message': f"Slow processing detected in {stage}: {stats['avg_duration_ms']}ms average",
                    'stage': stage,
                    'avg_duration': stats['avg_duration_ms']
                })

            if stats['success_rate'] < 95:  # < 95% success rate
                alerts.append({
                    'type': 'low_success_rate',
                    'severity': 'error',
                    'message': f"Low success rate in {stage}: {stats['success_rate']}%",
                    'stage': stage,
                    'success_rate': stats['success_rate']
                })

        # Check for high correction rates
        total_corrections = sum(
            stats['total_count']
            for stats in correction_stats.get('by_type', {}).values()
        )
        total_requests = sum(stats['total_count'] for stats in processing_stats.values())

        if total_requests > 0:
            correction_rate = (total_corrections / total_requests) * 100
            if correction_rate > 30:  # > 30% correction rate
                alerts.append({
                    'type': 'high_correction_rate',
                    'severity': 'warning',
                    'message': f"High correction rate detected: {correction_rate:.1f}%",
                    'correction_rate': correction_rate
                })

        # Check for filtering issues
        filtering_summary = filtering_stats.get('summary', {})
        rejection_rate = filtering_summary.get('rejection_rate', 0)

        if rejection_rate > 70:  # > 70% rejection rate
            alerts.append({
                'type': 'high_filtering_rejection_rate',
                'severity': 'error',
                'message': f"Very high filtering rejection rate: {rejection_rate:.1f}%",
                'rejection_rate': rejection_rate
            })
        elif rejection_rate > 50:  # > 50% rejection rate
            alerts.append({
                'type': 'moderate_filtering_rejection_rate',
                'severity': 'warning',
                'message': f"High filtering rejection rate: {rejection_rate:.1f}%",
                'rejection_rate': rejection_rate
            })

        # Check for specific filtering issues
        filtering_by_reason = filtering_stats.get('by_reason', {})

        # High length check failures might indicate user education needed
        length_check_stats = filtering_by_reason.get('length_check', {})
        if length_check_stats.get('total_count', 0) > 20:  # > 20 length failures
            alerts.append({
                'type': 'high_length_check_failures',
                'severity': 'info',
                'message': f"Many messages rejected for being too short: {length_check_stats['total_count']} instances",
                'count': length_check_stats['total_count']
            })

        # High work validation failures might indicate bot usage clarity needed
        work_validation_stats = filtering_by_reason.get('work_validation', {})
        if work_validation_stats.get('total_count', 0) > 15:  # > 15 work validation failures
            alerts.append({
                'type': 'high_work_validation_failures',
                'severity': 'info',
                'message': f"Many non-work messages detected: {work_validation_stats['total_count']} instances",
                'count': work_validation_stats['total_count']
            })

        return alerts

    def _start_system_metrics_task(self):
        """Start background task for collecting system metrics."""
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self._collect_system_metrics())
        except Exception as e:
            logger.warning(f"⚠️ Could not start system metrics task: {e}")

    async def _collect_system_metrics(self):
        """Periodic collection of system metrics."""
        while True:
            try:
                # Collect basic system metrics
                self.record_system_metric("timestamp", datetime.now().isoformat())

                # Add more system metrics as needed
                await asyncio.sleep(300)  # Every 5 minutes

            except Exception as e:
                logger.error(f"❌ Error collecting system metrics: {e}")
                await asyncio.sleep(60)  # Short sleep on error

    def export_metrics(self, format: str = "json", hours: int = 24) -> str:
        """Export metrics data in specified format."""
        if format.lower() == "json":
            dashboard_data = self.get_dashboard_data(hours)
            return json.dumps(dashboard_data, indent=2, ensure_ascii=False)
        else:
            raise ValueError(f"Unsupported export format: {format}")

# Global shared instance
_metrics_service = None

def get_metrics_service() -> MetricsService:
    """Get the global metrics service instance."""
    global _metrics_service
    if _metrics_service is None:
        _metrics_service = MetricsService()
    return _metrics_service

# Convenience functions for easy integration
def create_session(user_id: int, chat_id: int) -> str:
    """Create a metrics session."""
    return get_metrics_service().create_session(user_id, chat_id)

def timer(session_id: str, user_id: int, chat_id: int, stage: ProcessingStage):
    """Get a timing context manager."""
    return get_metrics_service().timer(session_id, user_id, chat_id, stage)

def record_correction(session_id: str, admin_user_id: int, message_id: str,
                     correction_type: CorrectionType, original_text: str,
                     corrected_text: str, processing_time_ms: int, **kwargs):
    """Record a correction metric."""
    return get_metrics_service().record_correction(
        session_id, admin_user_id, message_id, correction_type,
        original_text, corrected_text, processing_time_ms, **kwargs
    )

def record_filtered_message(session_id: str, user_id: int, chat_id: int,
                           message: str, reason: str, stage_failed: Optional[str] = None,
                           processing_time_ms: int = 0, **kwargs):
    """Record a filtered message metric."""
    return get_metrics_service().record_filtered_message(
        session_id, user_id, chat_id, message, reason, stage_failed, processing_time_ms, **kwargs
    )

def get_dashboard() -> Dict[str, Any]:
    """Get dashboard data."""
    return get_metrics_service().get_dashboard_data()