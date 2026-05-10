import logging
from datetime import datetime, timezone, timedelta
from .google_auth import build_google_service

logger = logging.getLogger(__name__)

# Google Fit standard sleep stage values (RFC defined)
_GOOGLE_STAGE_NAMES = {1: "awake", 2: "sleep", 3: "awake", 4: "light", 5: "deep", 6: "rem"}
_GOOGLE_ASLEEP = frozenset({2, 4, 5, 6})

# Samsung Health sleep stage values used in com.samsung.health.sleep_stage
_SAMSUNG_STAGE_NAMES = {40001: "awake", 40002: "light", 40003: "deep", 40004: "rem"}
_SAMSUNG_ASLEEP = frozenset({40002, 40003, 40004})


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

    def _sleep_window_ms(self) -> tuple[int, int]:
        """Yesterday noon UTC → today noon UTC: captures any overnight sleep period."""
        now = datetime.now(timezone.utc)
        today_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
        yesterday_noon = today_noon - timedelta(hours=24)
        return int(yesterday_noon.timestamp() * 1000), int(today_noon.timestamp() * 1000)

    def _find_sleep_sources(self) -> list[tuple[str, str]]:
        """List (stream_id, data_type) for all sleep data sources, sorted by priority."""
        try:
            resp = self._svc().users().dataSources().list(userId="me").execute()
        except Exception as exc:
            logger.warning("get_sleep: dataSources.list failed: %s", exc)
            return []
        sources = []
        for ds in resp.get("dataSource", []):
            stream_id = ds.get("dataStreamId", "")
            type_name = ds.get("dataType", {}).get("name", "")
            if "sleep" in stream_id.lower() or "sleep" in type_name.lower():
                sources.append((stream_id, type_name))
        # Google standard type first, then Samsung, then everything else
        sources.sort(key=lambda x: (
            0 if x[1] == "com.google.sleep.segment" else
            1 if "samsung" in x[0].lower() or "samsung" in x[1].lower() else
            2
        ))
        logger.info(
            "get_sleep: %d sleep source(s) available: %s",
            len(sources), [s[0] for s in sources] or "none",
        )
        return sources

    def _raw_points(self, stream_id: str, start_ms: int, end_ms: int) -> list[dict]:
        """Fetch raw data points from a data source for the given time range."""
        start_ns = start_ms * 1_000_000
        end_ns = end_ms * 1_000_000
        resp = self._svc().users().dataSources().datasets().get(
            userId="me",
            dataSourceId=stream_id,
            datasetId=f"{start_ns}-{end_ns}",
        ).execute()
        return resp.get("point", [])

    def _sum_sleep_points(self, points: list[dict], is_samsung: bool) -> dict:
        """Parse raw sleep data points into duration totals by stage."""
        stage_names = _SAMSUNG_STAGE_NAMES if is_samsung else _GOOGLE_STAGE_NAMES
        asleep = _SAMSUNG_ASLEEP if is_samsung else _GOOGLE_ASLEEP
        per_stage: dict[str, int] = {"light": 0, "deep": 0, "rem": 0, "awake": 0}
        total_ms = 0
        for pt in points:
            s_ns = int(pt.get("startTimeNanos", 0))
            e_ns = int(pt.get("endTimeNanos", 0))
            dur_ms = (e_ns - s_ns) // 1_000_000
            if dur_ms <= 0:
                continue
            val = next((v.get("intVal") for v in pt.get("value", [])), None)
            stage = stage_names.get(val)
            if stage in per_stage:
                per_stage[stage] += dur_ms
            if val in asleep:
                total_ms += dur_ms
        hours = total_ms // 3_600_000
        minutes = (total_ms % 3_600_000) // 60_000
        return {
            "hours": hours,
            "minutes": minutes,
            "total_minutes": total_ms // 60_000,
            "stages": {k: v // 60_000 for k, v in per_stage.items() if v > 0},
        }

    def _sleep_from_sessions(self, start_ms: int, end_ms: int) -> dict:
        """Sessions API fallback — returns total duration only, no stage breakdown."""
        start_iso = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat()
        end_iso = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).isoformat()
        resp = self._svc().users().sessions().list(
            userId="me",
            startTime=start_iso,
            endTime=end_iso,
            activityType=72,  # 72 = sleep
        ).execute()
        total_ms = sum(
            int(s.get("endTimeMillis", 0)) - int(s.get("startTimeMillis", 0))
            for s in resp.get("session", [])
        )
        hours = total_ms // 3_600_000
        minutes = (total_ms % 3_600_000) // 60_000
        logger.info("get_sleep: sessions fallback → %dh %dm", hours, minutes)
        return {"hours": hours, "minutes": minutes, "total_minutes": total_ms // 60_000, "stages": {}}

    def get_sleep(self) -> dict:
        start_ms, end_ms = self._sleep_window_ms()
        sources = self._find_sleep_sources()

        for stream_id, type_name in sources:
            try:
                points = self._raw_points(stream_id, start_ms, end_ms)
            except Exception as exc:
                logger.warning("get_sleep: %s query failed: %s", stream_id, exc)
                continue

            logger.info("get_sleep: %s → %d point(s)", stream_id, len(points))
            if not points:
                continue

            is_samsung = "samsung" in type_name.lower() or "samsung" in stream_id.lower()
            result = self._sum_sleep_points(points, is_samsung)

            if result["total_minutes"] > 0:
                logger.info(
                    "get_sleep: source=%s total=%dh%dm stages=%s",
                    stream_id, result["hours"], result["minutes"],
                    {k: f"{v}m" for k, v in result.get("stages", {}).items()},
                )
                return result

            # Points present but zero sleep — stage values weren't recognised;
            # log a sample so the mapping can be updated.
            sampled = {next((v.get("intVal") for v in pt.get("value", [])), None) for pt in points[:10]}
            logger.warning(
                "get_sleep: %s — %d point(s) but 0 sleep minutes; "
                "unrecognised stage values in sample: %s",
                stream_id, len(points), sampled,
            )

        # Fallback: sleep sessions give total duration without stage breakdown
        try:
            result = self._sleep_from_sessions(start_ms, end_ms)
            if result["total_minutes"] > 0:
                return result
        except Exception as exc:
            logger.warning("get_sleep: sessions fallback failed: %s", exc)

        logger.warning("get_sleep: no sleep data found in any source")
        return {"hours": 0, "minutes": 0, "total_minutes": 0, "stages": {}}

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


    @staticmethod
    def compute_energy_score(summary: dict) -> dict:
        """Return {"score": 0-100, "level": "low"|"medium"|"high"} from a get_summary() dict."""
        score = 0

        # Sleep: 0–40 pts (optimal 7–9 h)
        total_min = summary.get("sleep", {}).get("total_minutes") or 0
        hours = total_min / 60
        if 7 <= hours <= 9:
            score += 40
        elif hours > 9:
            score += 30
        elif 6 <= hours < 7:
            score += 28
        elif 5 <= hours < 6:
            score += 15
        elif 4 <= hours < 5:
            score += 7

        # Resting HR: 0–25 pts (lower = better; None = neutral 13)
        bpm = summary.get("heart_rate", {}).get("bpm")
        if bpm is None:
            score += 13
        elif bpm < 50:
            score += 25
        elif bpm < 60:
            score += 22
        elif bpm < 70:
            score += 18
        elif bpm < 80:
            score += 12
        elif bpm < 90:
            score += 6

        # Active minutes: 0–20 pts (linear, 60 min = full score)
        active = summary.get("active_minutes", {}).get("minutes") or 0
        score += min(20, int(active / 3))

        # Steps: 0–15 pts
        steps = summary.get("steps", {}).get("steps") or 0
        if steps >= 10_000:
            score += 15
        elif steps >= 7_500:
            score += 12
        elif steps >= 5_000:
            score += 8
        elif steps >= 2_500:
            score += 4
        elif steps >= 1_000:
            score += 2

        score = min(100, score)
        level = "high" if score >= 71 else ("medium" if score >= 40 else "low")
        return {"score": score, "level": level}


google_fit = GoogleFit()
