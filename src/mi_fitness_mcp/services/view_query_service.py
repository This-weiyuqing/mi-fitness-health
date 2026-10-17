"""健康页面汇总、分页及流式导出的只读服务。"""

from typing import Iterator

from mi_fitness_mcp.storage import Database
from mi_fitness_mcp.storage.view_queries import ViewRepository, ViewSelection, _check_page


class ViewQueryService:
    def __init__(self, db: Database, user_id: str):
        self.repository = ViewRepository(db, user_id)

    @staticmethod
    def _envelope(selection: ViewSelection) -> dict:
        return dict(status='ok', kind=selection.kind, range=dict(start=selection.start_date, end=selection.end_date))

    def get_view(self, selection: ViewSelection, page: int = 1) -> dict:
        _check_page(page)
        with self.repository.snapshot() as connection:
            statistics = self.repository.statistics(selection, connection)
            coverage = statistics.pop('coverage')
            return self._envelope(selection) | dict(statistics=statistics,
                points=self.repository.points(selection, connection), coverage=coverage, stride=selection.stride,
                page=self.repository.page(selection, page, connection))

    def get_page(self, selection: ViewSelection, page: int = 1) -> dict:
        _check_page(page)
        with self.repository.snapshot() as connection:
            return self._envelope(selection) | dict(page=self.repository.page(selection, page, connection))

    def get_overview(self, start_date: str, end_date: str) -> dict:
        selections = {kind: ViewSelection(kind, start_date, end_date,
            sample_type='resting' if kind == 'heartrate' else None) for kind in ('activity', 'heartrate', 'sleep', 'spo2', 'stress')}
        with self.repository.snapshot() as connection:
            statistics = {kind: self.repository.statistics(selection, connection) for kind, selection in selections.items()}
        activity, heart, sleep, spo2, stress = (statistics[kind] for kind in selections)
        return dict(steps=activity['primary_sum'], active_kcal=activity['total_active_kcal'],
            distance_m=activity['total_distance_m'], resting_mean_bpm=heart['resting_mean_bpm'],
            mean_daily_asleep_minutes=sleep['mean_daily_asleep_minutes'], mean_spo2_pct=spo2['primary_mean'],
            mean_stress=stress['primary_mean'], activity_days=activity['coverage'], sleep_days=sleep['coverage'],
            resting_count=heart['count'], spo2_count=spo2['count'])

    def iter_export(self, selection: ViewSelection) -> Iterator[dict]:
        with self.repository.snapshot() as connection:
            yield from self.repository.iter_records(selection, connection)
