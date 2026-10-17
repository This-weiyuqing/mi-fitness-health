"""Sync service for importing data from adapters to database."""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

from mi_fitness_mcp.adapters.base import DataAdapter
from mi_fitness_mcp.storage import Database

logger = logging.getLogger(__name__)


class SyncService:
    """Service for synchronizing data from adapters to local database."""

    def __init__(
        self,
        adapter: DataAdapter,
        db: Database,
        default_lookback_days: int = 30,
        chunk_days: int = 7,
    ):
        """Initialize sync service.

        Args:
            adapter: Data source adapter
            db: Database instance
        """
        self.adapter = adapter
        self.db = db
        self.default_lookback_days = default_lookback_days
        self.chunk_days = chunk_days
        self._owner_scope = {"user_id": adapter.user_id} if getattr(adapter, "user_id", None) else {}
        self._sync_lock = asyncio.Lock()
        self._sync_active = False

    @property
    def sync_in_progress(self) -> bool:
        return self._sync_active or self._sync_lock.locked()

    async def _iterate_records(self, records: Any) -> AsyncIterator[Any]:
        if hasattr(records, "__aiter__"):
            async for record in records:
                yield record
            return

        for record in records:
            yield record

    async def _persist_records(self, data_type: str, records: Any):
        """限制每批 200 条，并在线程中提交，避免磁盘等待堵住 HTTP 请求。"""
        batch = []
        async for record in self._iterate_records(records):
            batch.append(record)
            if len(batch) >= 200:
                results = await asyncio.to_thread(self.db.insert_records_batch, data_type, batch)
                for item, created in zip(batch, results, strict=True):
                    yield item, created
                batch = []
        if batch:
            results = await asyncio.to_thread(self.db.insert_records_batch, data_type, batch)
            for item, created in zip(batch, results, strict=True):
                yield item, created

    async def sync_data_type(
        self,
        data_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
        force_full: bool = False,
    ) -> dict:
        """Synchronize one type while preventing overlapping sync operations."""
        # Check and reserve without awaiting, making this atomic for tasks on this loop.
        if self._sync_active or self._sync_lock.locked():
            raise RuntimeError("Another synchronization is already in progress")
        self._sync_active = True
        try:
            async with self._sync_lock:
                return await self._sync_data_type_unlocked(
                    data_type, start_date, end_date, force_full
                )
        finally:
            self._sync_active = False

    async def _sync_data_type_unlocked(
        self,
        data_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
        force_full: bool = False,
    ) -> dict:
        """Synchronize a specific data type.

        Args:
            data_type: Type of data to sync (daily_activity, sleep, workouts, body_measurements)
            start_date: Start date (YYYY-MM-DD), defaults to 30 days ago
            end_date: End date (YYYY-MM-DD), defaults to today
            force_full: Force full sync ignoring last sync state

        Returns:
            Dict with sync statistics
        """
        if not self.adapter.is_connected():
            raise RuntimeError("Adapter not connected")

        # 获取上次同步状态，用于增量同步
        last_record_ts = None
        if not force_full:
            state = self.db.get_sync_state(data_type, **self._owner_scope)
            if state and state.get("last_record_timestamp"):
                last_record_ts = datetime.fromisoformat(state["last_record_timestamp"])

        zone = timezone(timedelta(hours=8)) if getattr(self.adapter, "region", None) in ("", "cn") else None
        if not end_date:
            end_date = datetime.now(zone).strftime("%Y-%m-%d")
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            start_dt = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
        except ValueError as exc:
            raise ValueError("Dates must use YYYY-MM-DD format") from exc
        if start_dt is None:
            start_dt = (
                datetime.combine((last_record_ts.astimezone(zone) if zone and last_record_ts.tzinfo else last_record_ts).date(), datetime.min.time())
                if last_record_ts
                else end_dt - timedelta(days=self.default_lookback_days - 1)
            )
            start_date = start_dt.strftime("%Y-%m-%d")
        if start_dt > end_dt:
            raise ValueError("start_date must not be after end_date")

        chunk_days = getattr(self, "chunk_days", 7)
        totals = {"added": 0, "updated": 0, "skipped": 0}
        chunks = []
        cursor = start_dt
        while cursor <= end_dt:
            chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_dt)
            chunk_start_text = cursor.strftime("%Y-%m-%d")
            chunk_end_text = chunk_end.strftime("%Y-%m-%d")
            try:
                result = await self._sync_range(data_type, chunk_start_text, chunk_end_text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                chunks.append(
                    {
                        "start_date": chunk_start_text,
                        "end_date": chunk_end_text,
                        "status": "error",
                        "error_code": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                return {
                    "status": "partial" if any(c.get("status") == "ok" for c in chunks) else "error",
                    "data_type": data_type,
                    **totals,
                    "start_date": start_date,
                    "end_date": end_date,
                    "chunks": chunks,
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                }
            for key in totals:
                totals[key] += result[key]
            chunks.append(
                {
                    "start_date": chunk_start_text,
                    "end_date": chunk_end_text,
                    "status": "ok",
                    "added": result["added"],
                    "updated": result["updated"],
                    "skipped": result["skipped"],
                }
            )
            cursor = chunk_end + timedelta(days=1)

        return {
            "status": "ok",
            "data_type": data_type,
            **totals,
            "start_date": start_date,
            "end_date": end_date,
            "chunks": chunks,
        }

    async def _sync_range(self, data_type: str, start_date: str, end_date: str) -> dict:
        added = 0
        updated = 0
        skipped = 0
        last_ts = None

        # 按数据类型执行同步
        if data_type == "daily_activity":
            records = self.adapter.iter_daily_activity(start_date, end_date)
            async for activity, created in self._persist_records(data_type, records):
                if created:
                    added += 1
                else:
                    updated += 1
                if last_ts is None or (activity.collected_at and activity.collected_at > last_ts):
                    last_ts = activity.collected_at

        elif data_type == "sleep":
            records = self.adapter.iter_sleep_sessions(start_date, end_date)
            async for sleep, created in self._persist_records(data_type, records):
                if created:
                    added += 1
                else:
                    updated += 1
                if last_ts is None or sleep.start_at > last_ts:
                    last_ts = sleep.start_at

        elif data_type == "workouts":
            records = self.adapter.iter_workouts(start_date, end_date)
            async for workout, created in self._persist_records(data_type, records):
                if created:
                    added += 1
                else:
                    updated += 1
                if last_ts is None or workout.start_at > last_ts:
                    last_ts = workout.start_at

        elif data_type == "body_measurements":
            records = self.adapter.iter_body_measurements(start_date, end_date)
            async for measurement, created in self._persist_records(data_type, records):
                if created:
                    added += 1
                else:
                    updated += 1
                if last_ts is None or measurement.timestamp > last_ts:
                    last_ts = measurement.timestamp

        elif data_type == "heart_rate":
            records = self.adapter.iter_heart_rate(start_date, end_date)
            async for sample, created in self._persist_records(data_type, records):
                if created:
                    added += 1
                else:
                    updated += 1
                if last_ts is None or sample.timestamp > last_ts:
                    last_ts = sample.timestamp

        elif data_type == "spo2":
            records = self.adapter.iter_spo2(start_date, end_date)
            async for sample, created in self._persist_records(data_type, records):
                if created:
                    added += 1
                else:
                    updated += 1
                if last_ts is None or sample.timestamp > last_ts:
                    last_ts = sample.timestamp

        elif data_type == "stress":
            records = self.adapter.iter_stress(start_date, end_date)
            async for sample, created in self._persist_records(data_type, records):
                if created:
                    added += 1
                else:
                    updated += 1
                if last_ts is None or sample.timestamp > last_ts:
                    last_ts = sample.timestamp

        elif data_type == "abnormal_heart_beat":
            records = self.adapter.iter_abnormal_heart_beat(start_date, end_date)
            async for event, created in self._persist_records(data_type, records):
                if created:
                    added += 1
                else:
                    updated += 1
                if last_ts is None or event.start_at > last_ts:
                    last_ts = event.start_at

        else:
            raise ValueError(f"Unknown data type: {data_type}")

        # 更新同步状态
        if last_ts:
            await asyncio.to_thread(self.db.update_sync_state, data_type, last_ts, **self._owner_scope)

        logger.info(
            f"Synced {data_type}: {added} added, {updated} updated, "
            f"range {start_date} to {end_date}"
        )

        return {
            "data_type": data_type,
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "start_date": start_date,
            "end_date": end_date,
        }

    def sync_data_type_sync(
        self,
        data_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
        force_full: bool = False,
    ) -> dict:
        """Synchronous wrapper for sync_data_type.

        Use this when calling from synchronous code.
        """
        return asyncio.run(self.sync_data_type(data_type, start_date, end_date, force_full))
