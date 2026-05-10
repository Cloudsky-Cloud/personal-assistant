import logging
from datetime import datetime, timezone, timedelta
from google.auth.transport.requests import AuthorizedSession
from .google_auth import build_google_service, get_credentials

logger = logging.getLogger(__name__)

# ── Health Connect REST API ────────────────────────────────────────────────────
_HC_BASE = "https://health.googleapis.com/v4/users/me"

# Sleep stage strings returned by Health Connect
_HC_ASLEEP_STAGES = frozenset({"SLEEPING", "LIGHT_SLEEP", "DEEP_SLEEP", "REM_SLEEP"})
_HC_STAGE_NORM = {
    "SLEEPING":    "sleep",
    "LIGHT_SLEEP": "light",
    "DEEP_SLEEP":  "deep",
    "REM_SLEEP":   "rem",
    "AWAKE_IN_BED": "awake",
    "OUT_OF_BED":   "awake",
}

# ── Google Fit fallback ────────────────────────────────────────────────────────
# Standard Google Fit sleep stage integer codes
_GOOGLE_STAGE_NAMES = {1: "awake", 2: "sleep", 3: "awake", 4: "light", 5: "deep", 6: "rem"}
_GOOGLE_ASLEEP = frozenset({2, 4, 5, 6})

# Samsung Health sleep stage codes (synced through Fit data sources)
_SAMSUNG_STAGE_NAMES = {40001: "awake", 40002: "light", 40003: "deep", 40004: "rem"}
_SAMSUNG_ASLEEP = frozenset({40002, 40003, 40004})

# Activity types that represent sleep sessions in Google Fit
_SLEEP_ACTIVITY_TYPES = frozenset({72, 109, 110, 111, 112})


class GoogleFit:
    STEP_GOAL = 10_000

    def __init__(self):
        self._service = None
        self._hc_sess = None

    # ── Shared helpers ─────────────────────────────────────────────────────────

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

    @staticmethod
    def _iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Health Connect: session and HTTP helpers ───────────────────────────────

    def _get_hc_session(self) -> AuthorizedSession:
        if self._hc_sess is None:
            self._hc_sess = AuthorizedSession(get_credentials())
        return self._hc_sess

    def _hc_get(self, path: str, params: dict | None = None) -> dict | None:
        try:
            resp = self._get_hc_session().get(
                f"{_HC_BASE}/{path}", params=params, timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Health Connect GET %s: %s", path, exc)
            return None

    def _hc_post(self, path: str, body: dict) -> dict | None:
        try:
            resp = self._get_hc_session().post(
                f"{_HC_BASE}/{path}", json=body, timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Health Connect POST %s: %s", path, exc)
            return None

    # ── Health Connect: data fetchers ─────────────────────────────────────────

    def _hc_sleep(self) -> dict:
        now = datetime.now(timezone.utc)
        start = self._iso(now - timedelta(hours=48))
        end = self._iso(now)

        data = self._hc_get("dataTypes/sleep/dataPoints", {"startTime": start, "endTime": end})
        if data is None:
            return {}

        points = data.get("dataPoints", [])
        logger.info("Health Connect sleep: %d dataPoint(s) in 48h window", len(points))
        for p in points:
            logger.info(
                "  hc sleep: %s → %s  stage=%s",
                p.get("startTime", "?"), p.get("endTime", "?"),
                p.get("sleepStage", p.get("stage", "?")),
            )

        if not points:
            return {}

        # Prefer the most recent 24 hours; if nothing there, use all points
        cutoff = self._iso(now - timedelta(hours=24))
        recent = [p for p in points if (p.get("startTime") or "") >= cutoff] or points

        total_ms = 0
        stages: dict[str, int] = {}
        for p in recent:
            try:
                s = datetime.fromisoformat(p["startTime"].replace("Z", "+00:00"))
                e = datetime.fromisoformat(p["endTime"].replace("Z", "+00:00"))
                dur_ms = int((e - s).total_seconds() * 1000)
                if dur_ms <= 0:
                    continue
                stage = p.get("sleepStage") or p.get("stage") or "SLEEPING"
                norm = _HC_STAGE_NORM.get(stage, "sleep")
                stages[norm] = stages.get(norm, 0) + dur_ms // 60_000
                if stage in _HC_ASLEEP_STAGES:
                    total_ms += dur_ms
            except Exception:
                pass

        hours = total_ms // 3_600_000
        minutes = (total_ms % 3_600_000) // 60_000
        logger.info("Health Connect sleep: %dh%dm (stages=%s)", hours, minutes, stages)
        return {"hours": hours, "minutes": minutes, "total_minutes": total_ms // 60_000, "stages": stages}

    def _hc_steps(self) -> dict:
        start_ms, end_ms = self._yesterday_ms()
        start = self._iso(datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc))
        end   = self._iso(datetime.fromtimestamp(end_ms   / 1000, tz=timezone.utc))

        # Try daily roll-up first (single aggregated value)
        data = self._hc_post("dataTypes/steps/dataPoints:dailyRollUp", {
            "startTime": start, "endTime": end,
        })
        if data and data.get("dataPoints"):
            steps = sum(
                p.get("value", {}).get("intVal", 0) or int(p.get("steps", 0))
                for p in data["dataPoints"]
            )
            logger.info("Health Connect steps (dailyRollUp): %d", steps)
            return {"steps": steps, "goal": self.STEP_GOAL, "goal_pct": round(steps / self.STEP_GOAL * 100)}

        # Fallback: raw data points
        data = self._hc_get("dataTypes/steps/dataPoints", {"startTime": start, "endTime": end})
        if not data:
            return {}
        points = data.get("dataPoints", [])
        steps = sum(p.get("value", {}).get("intVal", 0) or int(p.get("steps", 0)) for p in points)
        logger.info("Health Connect steps (raw points): %d from %d point(s)", steps, len(points))
        return {"steps": steps, "goal": self.STEP_GOAL, "goal_pct": round(steps / self.STEP_GOAL * 100)}

    def _hc_heart_rate(self) -> dict:
        start_ms, end_ms = self._yesterday_ms()
        start = self._iso(datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc))
        end   = self._iso(datetime.fromtimestamp(end_ms   / 1000, tz=timezone.utc))

        data = self._hc_get("dataTypes/heart_rate/dataPoints", {"startTime": start, "endTime": end})
        if not data:
            return {}
        points = data.get("dataPoints", [])
        logger.info("Health Connect heart_rate: %d point(s)", len(points))
        bpms = []
        for p in points:
            bpm = (
                p.get("value", {}).get("fpVal")
                or p.get("beatsPerMinute")
                or p.get("bpm")
            )
            if bpm:
                bpms.append(float(bpm))
        if not bpms:
            return {}
        return {"bpm": round(min(bpms))}  # min reading approximates resting HR

    def _hc_calories(self) -> dict:
        start_ms, end_ms = self._yesterday_ms()
        start = self._iso(datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc))
        end   = self._iso(datetime.fromtimestamp(end_ms   / 1000, tz=timezone.utc))

        data = self._hc_get("dataTypes/total_calories/dataPoints", {"startTime": start, "endTime": end})
        if not data:
            return {}
        points = data.get("dataPoints", [])
        calories = sum(
            p.get("value", {}).get("fpVal", 0) or float(p.get("calories", 0))
            for p in points
        )
        logger.info("Health Connect calories: %.0f from %d point(s)", calories, len(points))
        return {"calories": round(calories)}

    def _hc_active_minutes(self) -> dict:
        start_ms, end_ms = self._yesterday_ms()
        start = self._iso(datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc))
        end   = self._iso(datetime.fromtimestamp(end_ms   / 1000, tz=timezone.utc))

        data = self._hc_get("dataTypes/active_minutes/dataPoints", {"startTime": start, "endTime": end})
        if not data:
            return {}
        points = data.get("dataPoints", [])
        minutes = sum(p.get("value", {}).get("intVal", 0) or int(p.get("activeMinutes", 0)) for p in points)
        logger.info("Health Connect active_minutes: %d from %d point(s)", minutes, len(points))
        return {"minutes": minutes}

    # ── Google Fit fallback helpers ────────────────────────────────────────────

    def _svc(self):
        if self._service is None:
            self._service = build_google_service("fitness", "v1")
        return self._service

    def _aggregate(self, data_type: str, start_ms: int, end_ms: int) -> list[dict]:
        body = {
            "aggregateBy": [{"dataTypeName": data_type}],
            "bucketByTime": {"durationMillis": end_ms - start_ms},
            "startTimeMillis": start_ms,
            "endTimeMillis": end_ms,
        }
        result = self._svc().users().dataset().aggregate(userId="me", body=body).execute()
        return result.get("bucket", [])

    # ── Google Fit: sleep (three-tier fallback) ────────────────────────────────

    def _sessions_sleep(self, start_ms: int, end_ms: int) -> dict:
        start_iso = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat()
        end_iso   = datetime.fromtimestamp(end_ms   / 1000, tz=timezone.utc).isoformat()
        try:
            resp = self._svc().users().sessions().list(
                userId="me", startTime=start_iso, endTime=end_iso,
            ).execute()
        except Exception as exc:
            logger.warning("get_sleep[fit/sessions]: %s", exc)
            return {}

        all_sessions = resp.get("session", [])
        logger.info(
            "get_sleep[fit/sessions]: %d total session(s) in %s → %s",
            len(all_sessions), self._fmt_ms(start_ms), self._fmt_ms(end_ms),
        )
        for s in all_sessions:
            s_ms = int(s.get("startTimeMillis", 0))
            e_ms = int(s.get("endTimeMillis", 0))
            logger.info(
                "  session: activityType=%s name=%r start=%s dur=%dm",
                s.get("activityType"), s.get("name"),
                self._fmt_ms(s_ms), (e_ms - s_ms) // 60_000,
            )

        sleep_sessions = [s for s in all_sessions if s.get("activityType") in _SLEEP_ACTIVITY_TYPES]
        if not sleep_sessions:
            return {}

        sleep_sessions.sort(key=lambda s: int(s.get("startTimeMillis", 0)), reverse=True)
        best = sleep_sessions[0]
        total_ms = int(best.get("endTimeMillis", 0)) - int(best.get("startTimeMillis", 0))
        hours, minutes = total_ms // 3_600_000, (total_ms % 3_600_000) // 60_000
        logger.info(
            "get_sleep[fit/sessions]: activityType=%s → %dh%dm",
            best.get("activityType"), hours, minutes,
        )
        return {"hours": hours, "minutes": minutes, "total_minutes": total_ms // 60_000, "stages": {}}

    def _find_sleep_sources(self) -> list[tuple[str, str]]:
        try:
            resp = self._svc().users().dataSources().list(userId="me").execute()
        except Exception as exc:
            logger.warning("get_sleep[fit/sources]: dataSources.list failed: %s", exc)
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
        logger.info("get_sleep[fit/sources]: %d sleep source(s): %s", len(sources), [s[0] for s in sources] or "none")
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
                logger.warning("get_sleep[fit/sources]: %s failed: %s", stream_id, exc)
                continue
            logger.info("get_sleep[fit/sources]: %s → %d point(s)", stream_id, len(points))
            if not points:
                continue
            is_samsung = "samsung" in type_name.lower() or "samsung" in stream_id.lower()
            result = self._sum_sleep_points(points, is_samsung)
            if result["total_minutes"] > 0:
                return result
            sampled = {next((v.get("intVal") for v in pt.get("value", [])), None) for pt in points[:10]}
            logger.warning("get_sleep[fit/sources]: %s — 0 sleep min; sample values: %s", stream_id, sampled)
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
                logger.warning("get_sleep[fit/aggregate/%s]: %s", bucket_type, exc)
                continue
            buckets = resp.get("bucket", [])
            point_count = sum(len(ds.get("point", [])) for b in buckets for ds in b.get("dataset", []))
            logger.info("get_sleep[fit/aggregate/%s]: %d bucket(s), %d point(s)", bucket_type, len(buckets), point_count)

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

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_sleep(self) -> dict:
        # 1. Health Connect (primary — direct Galaxy Watch data via Health Connect)
        try:
            result = self._hc_sleep()
            if result.get("total_minutes", 0) > 0:
                logger.info("get_sleep: Health Connect returned %dh%dm", result["hours"], result["minutes"])
                return result
            logger.info("get_sleep: Health Connect returned no data, falling back to Google Fit")
        except Exception as exc:
            logger.warning("get_sleep: Health Connect error: %s", exc)

        # 2. Google Fit — Sessions API (what the Fit app uses)
        start_ms, end_ms = self._sleep_window_ms()
        logger.info("get_sleep: trying Google Fit — window %s → %s", self._fmt_ms(start_ms), self._fmt_ms(end_ms))

        result = self._sessions_sleep(start_ms, end_ms)
        if result.get("total_minutes", 0) > 0:
            try:
                enriched = self._datasource_sleep(start_ms, end_ms)
                if enriched.get("stages"):
                    result["stages"] = enriched["stages"]
            except Exception:
                pass
            return result

        # 3. Google Fit — Raw data source points
        result = self._datasource_sleep(start_ms, end_ms)
        if result.get("total_minutes", 0) > 0:
            return result

        # 4. Google Fit — Aggregate endpoint
        result = self._aggregate_sleep(start_ms, end_ms)
        if result.get("total_minutes", 0) > 0:
            return result

        logger.warning("get_sleep: no sleep data from Health Connect or any Google Fit approach")
        return {"hours": 0, "minutes": 0, "total_minutes": 0, "stages": {}}

    def get_steps(self) -> dict:
        # 1. Health Connect
        try:
            result = self._hc_steps()
            if result.get("steps", 0) > 0:
                logger.info("get_steps: Health Connect → %d steps", result["steps"])
                return result
        except Exception as exc:
            logger.warning("get_steps: Health Connect error: %s", exc)

        # 2. Google Fit fallback
        start_ms, end_ms = self._yesterday_ms()
        buckets = self._aggregate("com.google.step_count.delta", start_ms, end_ms)
        steps = sum(
            val.get("intVal", 0)
            for bucket in buckets
            for dataset in bucket.get("dataset", [])
            for point in dataset.get("point", [])
            for val in point.get("value", [])
        )
        logger.info("get_steps: Google Fit → %d steps", steps)
        return {"steps": steps, "goal": self.STEP_GOAL, "goal_pct": round(steps / self.STEP_GOAL * 100)}

    def get_heart_rate(self) -> dict:
        # 1. Health Connect
        try:
            result = self._hc_heart_rate()
            if result.get("bpm"):
                logger.info("get_heart_rate: Health Connect → %d bpm", result["bpm"])
                return result
        except Exception as exc:
            logger.warning("get_heart_rate: Health Connect error: %s", exc)

        # 2. Google Fit fallback
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
        bpm = round(min(rates))
        logger.info("get_heart_rate: Google Fit → %d bpm", bpm)
        return {"bpm": bpm}

    def get_calories(self) -> dict:
        # 1. Health Connect
        try:
            result = self._hc_calories()
            if result.get("calories", 0) > 0:
                logger.info("get_calories: Health Connect → %d kcal", result["calories"])
                return result
        except Exception as exc:
            logger.warning("get_calories: Health Connect error: %s", exc)

        # 2. Google Fit fallback
        start_ms, end_ms = self._yesterday_ms()
        buckets = self._aggregate("com.google.calories.expended", start_ms, end_ms)
        calories = sum(
            val.get("fpVal", 0.0)
            for bucket in buckets
            for dataset in bucket.get("dataset", [])
            for point in dataset.get("point", [])
            for val in point.get("value", [])
        )
        logger.info("get_calories: Google Fit → %.0f kcal", calories)
        return {"calories": round(calories)}

    def get_active_minutes(self) -> dict:
        # 1. Health Connect
        try:
            result = self._hc_active_minutes()
            if result.get("minutes", 0) > 0:
                logger.info("get_active_minutes: Health Connect → %d min", result["minutes"])
                return result
        except Exception as exc:
            logger.warning("get_active_minutes: Health Connect error: %s", exc)

        # 2. Google Fit fallback
        start_ms, end_ms = self._yesterday_ms()
        buckets = self._aggregate("com.google.active_minutes", start_ms, end_ms)
        minutes = sum(
            val.get("intVal", 0)
            for bucket in buckets
            for dataset in bucket.get("dataset", [])
            for point in dataset.get("point", [])
            for val in point.get("value", [])
        )
        logger.info("get_active_minutes: Google Fit → %d min", minutes)
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
