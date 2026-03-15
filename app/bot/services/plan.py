import json
import logging
from pathlib import Path

from app.bot.models import Plan
from app.config import BASE_DIR, DEFAULT_PLANS_DIR

logger = logging.getLogger(__name__)


class PlanService:
    def __init__(self) -> None:
        file_path = self._resolve_file_path()

        try:
            with file_path.open("r", encoding="utf-8") as f:
                self.data = json.load(f)
            logger.info(f"Loaded plans data from '{file_path}'.")
        except json.JSONDecodeError:
            logger.error(f"Failed to parse file '{file_path}'. Invalid JSON format.")
            raise ValueError(f"File '{file_path}' is not a valid JSON file.")

        if "plans" not in self.data or not isinstance(self.data["plans"], list):
            logger.error(f"'plans' key is missing or not a list in '{file_path}'.")
            raise ValueError(f"'plans' key is missing or not a list in '{file_path}'.")

        if "durations" not in self.data or not isinstance(self.data["durations"], list):
            logger.error(f"'durations' key is missing or not a list in '{file_path}'.")
            raise ValueError(f"'durations' key is missing or not a list in '{file_path}'.")

        self._plans: list[Plan] = [Plan.from_dict(plan) for plan in self.data["plans"]]
        self._plans_by_code: dict[str, Plan] = {plan.code: plan for plan in self._plans}
        self._durations: list[int] = self.data["durations"]
        logger.info("Plans loaded successfully.")

    def _resolve_file_path(self) -> Path:
        candidates = (
            DEFAULT_PLANS_DIR,
            BASE_DIR.parent / "plans.json",
            BASE_DIR.parent / "plans.example.json",
        )

        for candidate in candidates:
            if candidate.is_file():
                if candidate != DEFAULT_PLANS_DIR:
                    logger.warning(
                        "Primary plans file '%s' was not found. Using fallback '%s'.",
                        DEFAULT_PLANS_DIR,
                        candidate,
                    )
                return candidate

        checked_files = ", ".join(str(candidate) for candidate in candidates)
        logger.error("No plans file found. Checked: %s", checked_files)
        raise FileNotFoundError(f"No plans file found. Checked: {checked_files}")

    def get_plan(self, devices: int) -> Plan | None:
        plan = next(
            (plan for plan in self._plans if plan.devices == devices and plan.is_public),
            None,
        )

        if not plan:
            logger.critical(f"Plan with {devices} devices not found.")

        return plan

    def get_plan_by_code(self, code: str | None) -> Plan | None:
        if not code:
            return None

        plan = self._plans_by_code.get(code)
        if not plan:
            logger.warning("Plan with code '%s' not found.", code)
        return plan

    def get_upgrade_plan(self, current_plan: Plan | str | None) -> Plan | None:
        if isinstance(current_plan, str):
            current_plan = self.get_plan_by_code(current_plan)

        if not current_plan:
            return None

        return next(
            (plan for plan in self._plans if plan.upgrade_from == current_plan.code),
            None,
        )

    def get_all_plans(self) -> list[Plan]:
        return [plan for plan in self._plans if plan.is_public]

    def get_durations(self) -> list[int]:
        return self._durations
