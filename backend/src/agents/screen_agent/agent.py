class MockScreenAgent:
    """Offline screen agent that keeps the first candidate."""

    def run(self, input_data: dict) -> dict:
        candidate_ids = list(input_data.get("candidate_paper_ids") or [])
        candidates = list(input_data.get("candidates") or [])

        selected_id = candidate_ids[0] if candidate_ids else None
        selected_paper = candidates[0] if candidates else None

        return {
            "ok": selected_id is not None or selected_paper is not None,
            "message": "mock screen success" if candidate_ids or candidates else "no candidates to screen",
            "screened_paper_ids": [selected_id] if selected_id else [],
            "selected_paper": selected_paper,
            "rejected_count": max(len(candidate_ids or candidates) - 1, 0),
            "screen_summary": "Mock screen kept 1 paper." if candidate_ids or candidates else "Mock screen found no papers.",
        }


class RealScreenAgent:
    """Placeholder for the future real screening agent."""

    def run(self, input_data: dict) -> dict:
        return {
            "ok": False,
            "message": "real screen_agent is not implemented",
            "screened_paper_ids": [],
            "selected_paper": None,
            "screen_summary": "Real screen agent is not implemented.",
        }


__all__ = ["MockScreenAgent", "RealScreenAgent"]
