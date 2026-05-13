import logging
from datetime import datetime, timezone, timedelta
from .google_auth import build_google_service

logger = logging.getLogger(__name__)

# Standard Google Fit sleep stage integer codes
_GOOGLE_STAGE_NAMES = {1: "awake", 2: "sleep", 3: "awake", 4: "light", 5: "deep", 6: "rem"}
_GOOGLE_ASLEEP = frozenset({2, 4, 5, 6})

# Samsung Health sleep stage codes (synced through Fit data sources)
_SAMSUNG_STAGE_NAMES = {40001: "awake", 40002: "light", 40003: "deep", 40004: "rem"}
_SAMSUNG_ASLEEP = frozenset({40002, 40003, 40004})

# Activity types that represent sleep sessions in Google Fit
_SLEEP_ACTIVITY_TYPES = frozenset({72, 109, 110, 111, 112})

# Sessions ended more than this many hours ago are flagged stale (sync likely broken)
_SLEEP_STALE_HOURS = 20


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

    def _sleep_window_ms(self) -> tuple[int, int]:
        now = datetime.now(timezone.utc)
        return int((now - timedelta(hours=48)).timestamp() * 1000), int(now.timestamp() * 1000)

    def _fmt_ms(self, ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def _aggregate(self, data_type: str, start_ms: int, end_ms: int) -> list[dict]:
        body = {
            "aggregateBy": [{"dataTypeName": data_type}],
            "bucketByTime": {"durationMillis": end_ms - start_ms},
            "startTimeMillis": start_ms,
            "endTimeMillis": end_ms,
        }
        result = self._svc().users().dataset().aggregate(userId="me", body=body).execute()
        return result.get("bucket", [])

    # ── Debug: raw data dump ───────────────────────────────────────────────────

    def debug_data_sources(self) -> list[dict]:
        """Return all data sources as raw dicts."""
        resp = self._svc().users().dataSources().list(userId="me").execute()
        return resp.get("dataSource", [])

    def debug_sessions(self, days: int = 7) -> list[dict]:
        """Return all sessions from the past N days as raw dicts."""
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=days)).isoformat()
        end = now.isoformat()
        resp = self._svc().users().sessions().list(
            userId="me", startTime=start, endTime=end,
        ).execute()
        return resp.get("session", [])

    # ── Sleep: three-tier approach ─────────────────────────────────────────────

    def _sessions_sleep(self, start_ms: int, end_ms: int) -> dict:
        start_iso = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat()
        end_iso   = datetime.fromtimestamp(end_ms   / 1000, tz=timezone.utc).isoformat()
        try:
            resp = self._svc().users().sessions().list(
                userId="me", startTime=start_iso, endTime=end_iso,
            ).execute()
        except Exception as exc:
            logger.warning("get_sleep[sessions]: %s", exc)
            return {}

        all_sessions = resp.get("session", [])
        logger.info(
            "get_sleep[sessions]: %d total session(s) in %s → %s",
            len(all_sessions), self._fmt_ms(start_ms), self._fmt_ms(end_ms),
        )
        for s in all_sessions:
            s_ms = int(s.get("startTimeMillis", 0))
            e_ms = int(s.get("endTimeMillis", 0))
            logger.info(
                "  session activityType=%s name=%r start=%s dur=%dm id=%s",
                s.get("activityType"), s.get("name"),
                self._fmt_ms(s_ms), (e_ms - s_ms) // 60_000, s.get("id", "")[:24],
            )

        sleep_sessions = [s for s in all_sessions if s.get("activityType") in _SLEEP_ACTIVITY_TYPES]
        logger.info(
            "get_sleep[sessions]: %d sleep session(s) (activityType in %s)",
            len(sleep_sessions), sorted(_SLEEP_ACTIVITY_TYPES),
        )
        if not sleep_sessions:
            return {}

        sleep_sessions.sort(key=lambda s: int(s.get("startTimeMillis", 0)), reverse=True)
        best = sleep_sessions[0]
        end_time_ms = int(best.get("endTimeMillis", 0))
        total_ms = end_time_ms - int(best.get("startTimeMillis", 0))
        hours, minutes = total_ms // 3_600_000, (total_ms % 3_600_000) // 60_000
        logger.info(
            "get_sleep[sessions]: using activityType=%s → %dh%dm",
            best.get("activityType"), hours, minutes,
        )
        in_bed_minutes = total_ms // 60_000
        return {
            "hours": hours, "minutes": minutes, "total_minutes": in_bed_minutes,
            "in_bed_minutes": in_bed_minutes,
            "stages": {}, "_session_end_ms": end_time_ms,
        }

    def _find_sleep_sources(self) -> list[tuple[str, str]]:
        try:
            resp = self._svc().users().dataSources().list(userId="me").execute()
        except Exception as exc:
            logger.warning("get_sleep[sources]: dataSources.list failed: %s", exc)
            return []
        sources = []
        for ds in resp.get("dataSource", []):
            stream_id = ds.get("dataStreamId", "")
            type_name = ds.get("dataType", {}).get("name", "")
            if "sleep" in stream_id.lower() or "sleep" in type_name.lower():
                sources.append((stream_id, type_name))
        sources.sort(key=lambda x: (
            0 if x[1] == "com.google.sleep.segment" else
            1 if "samsung" in x[0].lower() or "samsung" in x[1].lower() else 2
        ))
        logger.info("get_sleep[sources]: %d sleep source(s): %s", len(sources), [s[0] for s in sources] or "none")
        return sources

    def _raw_points(self, stream_id: str, start_ms: int, end_ms: int) -> list[dict]:
        start_ns, end_ns = start_ms * 1_000_000, end_ms * 1_000_000
        resp = self._svc().users().dataSources().datasets().get(
            userId="me", dataSourceId=stream_id, datasetId=f"{start_ns}-{end_ns}",
        ).execute()
        return resp.get("point", [])

    def _sum_sleep_points(self, points: list[dict], is_samsung: bool) -> dict:
        stage_names = _SAMSUNG_STAGE_NAMES if is_samsung else _GOOGLE_STAGE_NAMES
        asleep      = _SAMSUNG_ASLEEP      if is_samsung else _GOOGLE_ASLEEP
        per_stage: dict[str, int] = {"light": 0, "deep": 0, "rem": 0, "awake": 0}
        total_ms = 0
        for pt in points:
            dur_ms = (int(pt.get("endTimeNanos", 0)) - int(pt.get("startTimeNanos", 0))) // 1_000_000
            if dur_ms <= 0:
                continue
            val = next((v.get("intVal") for v in pt.get("value", [])), None)
            stage = stage_names.get(val)
            if stage in per_stage:
                per_stage[stage] += dur_ms
            if val in asleep:
                total_ms += dur_ms
        hours, minutes = total_ms // 3_600_000, (total_ms % 3_600_000) // 60_000
        return {
            "hours": hours, "minutes": minutes, "total_minutes": total_ms // 60_000,
            "stages": {k: v // 60_000 for k, v in per_stage.items() if v > 0},
        }

    def _datasource_sleep(self, start_ms: int, end_ms: int) -> dict:
        for stream_id, type_name in self._find_sleep_sources():
            try:
                points = self._raw_points(stream_id, start_ms, end_ms)
            except Exception as exc:
                logger.warning("get_sleep[sources]: %s failed: %s", stream_id, exc)
                continue
            logger.info("get_sleep[sources]: %s → %d point(s)", stream_id, len(points))
            if not points:
                continue
            is_samsung = "samsung" in type_name.lower() or "samsung" in stream_id.lower()
            result = self._sum_sleep_points(points, is_samsung)
            if result["total_minutes"] > 0:
                return result
            sampled = {next((v.get("intVal") for v in pt.get("value", [])), None) for pt in points[:10]}
            logger.warning("get_sleep[sources]: %s — 0 sleep min; sample stage values: %s", stream_id, sampled)
        return {}

    def _aggregate_sleep(self, start_ms: int, end_ms: int) -> dict:
        for body in [
            {
                "aggregateBy": [{"dataTypeName": "com.google.sleep.segment"}],
                "bucketByActivityType": {"minDurationMillis": 60_000},
                "startTimeMillis": start_ms, "endTimeMillis": end_ms,
            },
            {
                "aggregateBy": [{"dataTypeName": "com.google.sleep.segment"}],
                "bucketByTime": {"durationMillis": end_ms - start_ms},
                "startTimeMillis": start_ms, "endTimeMillis": end_ms,
            },
        ]:
            bucket_type = "bucketByActivityType" if "bucketByActivityType" in body else "bucketByTime"
            try:
                resp = self._svc().users().dataset().aggregate(userId="me", body=body).execute()
            except Exception as exc:
                logger.warning("get_sleep[aggregate/%s]: %s", bucket_type, exc)
                continue
            buckets = resp.get("bucket", [])
            point_count = sum(len(ds.get("point", [])) for b in buckets for ds in b.get("dataset", []))
            logger.info("get_sleep[aggregate/%s]: %d bucket(s), %d point(s)", bucket_type, len(buckets), point_count)

            per_stage: dict[str, int] = {"light": 0, "deep": 0, "rem": 0, "awake": 0}
            total_ms = 0
            for bucket in buckets:
                for ds in bucket.get("dataset", []):
                    for pt in ds.get("point", []):
                        dur_ms = (int(pt.get("endTimeNanos", 0)) - int(pt.get("startTimeNanos", 0))) // 1_000_000
                        if dur_ms <= 0:
                            continue
                        val = next((v.get("intVal") for v in pt.get("value", [])), None)
                        stage = _GOOGLE_STAGE_NAMES.get(val)
                        if stage in per_stage:
                            per_stage[stage] += dur_ms
                        if val in _GOOGLE_ASLEEP:
                            total_ms += dur_ms
            if total_ms > 0:
                hours, minutes = total_ms // 3_600_000, (total_ms % 3_600_000) // 60_000
                return {
                    "hours": hours, "minutes": minutes, "total_minutes": total_ms // 60_000,
                    "stages": {k: v // 60_000 for k, v in per_stage.items() if v > 0},
                }
        return {}

    def get_sleep(self) -> dict:
        start_ms, end_ms = self._sleep_window_ms()
        logger.info("get_sleep: window %s → %s", self._fmt_ms(start_ms), self._fmt_ms(end_ms))

        result = self._sessions_sleep(start_ms, end_ms)
        if result.get("total_minutes", 0) > 0:
            session_end_ms = result.pop("_session_end_ms", None)
            if session_end_ms:
                age_h = (datetime.now(timezone.utc).timestamp() * 1000 - session_end_ms) / 3_600_000
                if age_h > _SLEEP_STALE_HOURS:
                    result["stale"] = True
                    logger.warning("get_sleep: session ended %.1fh ago — flagging stale", age_h)
            # in_bed_minutes = full session span; total_minutes will be updated to actual sleep
            result.setdefault("in_bed_minutes", result["total_minutes"])
            try:
                enriched = self._datasource_sleep(start_ms, end_ms)
                if enriched.get("stages"):
                    result["stages"] = enriched["stages"]
                    if enriched.get("total_minutes", 0) > 0:
                        # Update total_minutes to reflect actual sleep (not in-bed time)
                        result["total_minutes"] = enriched["total_minutes"]
                        result["hours"] = enriched["hours"]
                        result["minutes"] = enriched["minutes"]
            except Exception:
                pass
            return result

        result = self._datasource_sleep(start_ms, end_ms)
        if result.get("total_minutes", 0) > 0:
            return result

        result = self._aggregate_sleep(start_ms, end_ms)
        if result.get("total_minutes", 0) > 0:
            return result

        logger.warning("get_sleep: no data from sessions, data sources, or aggregate")
        return {"unavailable": True}

    # ── Other metrics ──────────────────────────────────────────────────────────

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
            return {"bpm": None, "unavailable": True}
        return {"bpm": round(min(rates))}

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
            ("steps",          self.get_steps),
            ("sleep",          self.get_sleep),
            ("heart_rate",     self.get_heart_rate),
            ("calories",       self.get_calories),
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

        active = summary.get("active_minutes", {}).get("minutes") or 0
        score += min(20, int(active / 3))

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

    @staticmethod
    def compute_sleep_score(sleep: dict) -> dict:
        """Return {"score": 0-100, "label": "Poor"|"Fair"|"Good"|"Excellent"} from sleep data."""
        if sleep.get("unavailable") or not sleep:
            return {"score": None, "label": None}

        total_min = sleep.get("total_minutes") or 0
        hours = total_min / 60

        if 7 <= hours <= 9:
            score = 70
        elif hours > 9:
            score = 60
        elif 6 <= hours < 7:
            score = 50
        elif 5 <= hours < 6:
            score = 35
        elif 4 <= hours < 5:
            score = 20
        elif hours > 0:
            score = max(5, int(hours * 5))
        else:
            return {"score": None, "label": None}

        stages = sleep.get("stages", {})
        if stages and total_min > 0:
            deep_min = stages.get("deep", 0)
            rem_min = stages.get("rem", 0)
            deep_pct = deep_min / total_min * 100
            rem_pct = rem_min / total_min * 100
            if deep_pct >= 20:
                score += 15
            elif deep_pct >= 13:
                score += 10
            elif deep_pct >= 8:
                score += 5
            if rem_pct >= 22:
                score += 15
            elif rem_pct >= 15:
                score += 10
            elif rem_pct >= 10:
                score += 5

        score = min(100, score)
        if score >= 90:
            label = "Excellent"
        elif score >= 75:
            label = "Good"
        elif score >= 60:
            label = "Fair"
        else:
            label = "Poor"
        return {"score": score, "label": label}


google_fit = GoogleFit()
