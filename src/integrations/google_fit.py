from datetime import datetime, timezone, timedelta
from .google_auth import build_google_service


class GoogleFit:
    STEP_GOAL = 10_000

    def __init__(self):
        self._service = None

    def _svc(self):
        if self._service is None:
            self._service = build_google_service("fitness", "v1")
        return self._service

    def _yesterday_ms(self) -> tuple[int, int]:
        now = datetime.now(timezone.utc)
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_midnight = today_midnight - timedelta(days=1)
        return int(yesterday_midnight.timestamp() * 1000), int(today_midnight.timestamp() * 1000)

    def _aggregate(self, data_type: str, start_ms: int, end_ms: int) -> list[dict]:
        body = {
            "aggregateBy": [{"dataTypeName": data_type}],
            "bucketByTime": {"durationMillis": end_ms - start_ms},
            "startTimeMillis": start_ms,
            "endTimeMillis": end_ms,
        }
        result = self._svc().users().dataset().aggregate(userId="me", body=body).execute()
        return result.get("bucket", [])

    def get_steps(self) -> dict:
        start_ms, end_ms = self._yesterday_ms()
        buckets = self._aggregate("com.google.step_count.delta", start_ms, end_ms)
        steps = sum(
            val.get("intVal", 0)
            for bucket in buckets
            for dataset in bucket.get("dataset", [])
            for point in dataset.get("point", [])
            for val in point.get("value", [])
        )
        return {"steps": steps, "goal": self.STEP_GOAL, "goal_pct": round(steps / self.STEP_GOAL * 100)}

    def get_sleep(self) -> dict:
        now = datetime.now(timezone.utc)
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # Window: yesterday 6 PM UTC → today 11 AM UTC captures overnight sleep
        window_start = today_midnight - timedelta(hours=18)
        window_end = today_midnight + timedelta(hours=11)
        start_ms = int(window_start.timestamp() * 1000)
        end_ms = int(window_end.timestamp() * 1000)

        buckets = self._aggregate("com.google.sleep.segment", start_ms, end_ms)
        total_ms = 0
        for bucket in buckets:
            for dataset in bucket.get("dataset", []):
                for point in dataset.get("point", []):
                    sleep_val = next(
                        (v.get("intVal") for v in point.get("value", [])),
                        None,
                    )
                    # Stages: 2=sleep, 4=light, 5=deep, 6=REM (exclude 1=awake, 3=out-of-bed)
                    if sleep_val in (2, 4, 5, 6):
                        start_ns = int(point.get("startTimeNanos", 0))
                        end_ns = int(point.get("endTimeNanos", 0))
                        total_ms += (end_ns - start_ns) // 1_000_000

        hours = total_ms // 3_600_000
        minutes = (total_ms % 3_600_000) // 60_000
        return {"hours": hours, "minutes": minutes, "total_minutes": total_ms // 60_000}

    def get_heart_rate(self) -> dict:
        start_ms, end_ms = self._yesterday_ms()
        buckets = self._aggregate("com.google.heart_rate.bpm", start_ms, end_ms)
        rates = [
            val["fpVal"]
            for bucket in buckets
            for dataset in bucket.get("dataset", [])
            for point in dataset.get("point", [])
            for val in point.get("value", [])
            if val.get("fpVal")
        ]
        if not rates:
            return {"bpm": None}
        return {"bpm": round(min(rates))}  # min reading ≈ resting HR

    def get_calories(self) -> dict:
        start_ms, end_ms = self._yesterday_ms()
        buckets = self._aggregate("com.google.calories.expended", start_ms, end_ms)
        calories = sum(
            val.get("fpVal", 0.0)
            for bucket in buckets
            for dataset in bucket.get("dataset", [])
            for point in dataset.get("point", [])
            for val in point.get("value", [])
        )
        return {"calories": round(calories)}

    def get_active_minutes(self) -> dict:
        start_ms, end_ms = self._yesterday_ms()
        buckets = self._aggregate("com.google.active_minutes", start_ms, end_ms)
        minutes = sum(
            val.get("intVal", 0)
            for bucket in buckets
            for dataset in bucket.get("dataset", [])
            for point in dataset.get("point", [])
            for val in point.get("value", [])
        )
        return {"minutes": minutes}

    def get_summary(self) -> dict:
        results = {}
        for key, method in [
            ("steps", self.get_steps),
            ("sleep", self.get_sleep),
            ("heart_rate", self.get_heart_rate),
            ("calories", self.get_calories),
            ("active_minutes", self.get_active_minutes),
        ]:
            try:
                results[key] = method()
            except Exception:
                results[key] = {}
        return results


google_fit = GoogleFit()
