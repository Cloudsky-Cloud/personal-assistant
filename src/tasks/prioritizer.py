from dataclasses import dataclass
from typing import Optional


_URGENCY_KEYWORDS: dict[str, float] = {
    "critical": 0.9,
    "urgent": 0.9,
    "asap": 0.9,
    "emergency": 1.0,
    "outage": 0.9,
    "down": 0.8,
    "broken": 0.8,
    "deadline": 0.75,
    "today": 0.8,
    "overdue": 0.95,
    "immediate": 0.9,
    "now": 0.8,
}

_IMPORTANCE_KEYWORDS: dict[str, float] = {
    "revenue": 0.9,
    "client": 0.85,
    "customer": 0.85,
    "board": 0.9,
    "boss": 0.85,
    "ceo": 0.9,
    "production": 0.85,
    "outage": 0.9,
    "health": 0.85,
    "security": 0.85,
    "legal": 0.9,
    "contract": 0.8,
    "launch": 0.85,
    "release": 0.8,
    "interview": 0.75,
    "presentation": 0.75,
    "report": 0.7,
}

_IMPORTANCE_PENALTIES: dict[str, float] = {
    "bookmark": -0.3,
    "reorganize": -0.2,
    "clean up": -0.2,
    "someday": -0.3,
    "nice to have": -0.4,
    "optional": -0.3,
    "maybe": -0.2,
}


@dataclass
class TaskScore:
    urgency: float
    importance: float
    priority: float
    quadrant: str  # do_now | schedule | delegate | eliminate


class Prioritizer:
    def score(
        self,
        title: str,
        description: str = "",
        due_in_hours: Optional[float] = None,
    ) -> TaskScore:
        text = f"{title} {description}".lower()

        urgency = self._keyword_score(text, _URGENCY_KEYWORDS, base=0.3)
        if due_in_hours is not None:
            urgency = max(urgency, self._due_urgency(due_in_hours))

        importance = self._keyword_score(text, _IMPORTANCE_KEYWORDS, base=0.4)
        for kw, delta in _IMPORTANCE_PENALTIES.items():
            if kw in text:
                importance = max(0.05, importance + delta)

        urgency = round(min(1.0, max(0.0, urgency)), 4)
        importance = round(min(1.0, max(0.0, importance)), 4)
        priority = round((urgency + importance) / 2, 4)
        quadrant = self._quadrant(urgency, importance)
        return TaskScore(
            urgency=urgency,
            importance=importance,
            priority=priority,
            quadrant=quadrant,
        )

    def score_list(self, tasks: list[dict]) -> list[dict]:
        results = []
        for t in tasks:
            s = self.score(
                title=t.get("title", ""),
                description=t.get("description", ""),
                due_in_hours=t.get("due_in_hours"),
            )
            results.append({**t, "score": s})
        results.sort(key=lambda x: x["score"].priority, reverse=True)
        return results

    def _keyword_score(self, text: str, keywords: dict[str, float], base: float) -> float:
        score = base
        for kw, boost in keywords.items():
            if kw in text:
                score = max(score, boost)
        return score

    def _due_urgency(self, hours: float) -> float:
        if hours <= 0:
            return 1.0
        if hours <= 2:
            return 0.95
        if hours <= 8:
            return 0.85
        if hours <= 24:
            return 0.75
        if hours <= 72:
            return 0.55
        return 0.3

    def _quadrant(self, urgency: float, importance: float) -> str:
        u_high = urgency >= 0.6
        i_high = importance >= 0.6
        if u_high and i_high:
            return "do_now"
        if not u_high and i_high:
            return "schedule"
        if u_high and not i_high:
            return "delegate"
        return "eliminate"


prioritizer = Prioritizer()
