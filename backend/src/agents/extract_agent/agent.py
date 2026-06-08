class MockExtractAgent:
    """Offline extraction agent used by graph smoke tests."""

    def run(self, input_data: dict) -> dict:
        selected_paper = input_data.get("selected_paper") or {}
        paper_ids = list(input_data.get("screened_paper_ids") or [])
        paper_id = selected_paper.get("paper_id") or (paper_ids[0] if paper_ids else "mock-paper-001")
        pdf_path = input_data.get("pdf_path") or selected_paper.get("pdf_path") or "fake.pdf"
        pdf_name = input_data.get("pdf_name") or selected_paper.get("pdf_name") or pdf_path
        record_id = f"{paper_id}-record-001"

        return {
            "ok": True,
            "message": "mock extract success",
            "extracted_record_ids": [record_id],
            "extract_summary": "Mock extract produced 1 structured record.",
            "extraction": {
                "record_id": record_id,
                "paper_id": paper_id,
                "pdf_path": pdf_path,
                "pdf_name": pdf_name,
                "title": selected_paper.get("title") or "Mock Paper Title",
                "doi": "10.0000/mock",
                "summary_functions": ["adsorption"],
            },
        }


class RealExtractAgent:
    """Wrapper placeholder for the migrated real extract implementation."""

    def run(self, input_data: dict) -> dict:
        selected_paper = input_data.get("selected_paper") or {}
        pdf_path = input_data.get("pdf_path") or selected_paper.get("pdf_path")

        if not pdf_path:
            return {
                "ok": False,
                "message": "missing pdf_path for real extract_agent",
                "extracted_record_ids": [],
                "extraction": None,
            }

        try:
            from .text_agent import TextAgent
        except Exception as exc:
            return {
                "ok": False,
                "message": f"real extract_agent import failed: {exc}",
                "extracted_record_ids": [],
                "extraction": None,
            }

        agent = TextAgent()
        ok, error = agent.run(pdf_path)
        return {
            "ok": ok,
            "message": "real extract success" if ok else error,
            "extracted_record_ids": [],
            "extraction": agent.last_result if ok else None,
        }


__all__ = ["MockExtractAgent", "RealExtractAgent"]
