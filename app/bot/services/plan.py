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
        self._public_plans_by_offer_key: dict[tuple[int, bool], Plan] = {}
        for plan in self._plans:
            if not plan.is_public:
                continue
            self._public_plans_by_offer_key.setdefault(plan.commercial_key, plan)
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

    def get_plan(
        self,
        devices: int,
        *,
        includes_additional_profile: bool = False,
    ) -> Plan | None:
        plan = self._public_plans_by_offer_key.get((devices, includes_additional_profile))

        if not plan:
            logger.critical(
                "Plan with %s devices and additional_profile=%s not found.",
                devices,
                includes_additional_profile,
            )

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

    @staticmethod
    def _public_plan_sort_key(
        plan: Plan,
        *,
        prefer_additional_profile: bool = False,
    ) -> tuple[int, int, str]:
        return (
            0 if plan.includes_additional_profile == prefer_additional_profile else 1,
            plan.devices,
            plan.code,
        )

    def get_public_plan_equivalent(self, plan: Plan | str | None) -> Plan | None:
        if isinstance(plan, str):
            plan = self.get_plan_by_code(plan)

        if not plan:
            return None
        if plan.is_public:
            return plan

        return self._public_plans_by_offer_key.get(plan.commercial_key)

    def _is_plan_available_for_currency(self, plan: Plan, currency: str, duration: int) -> bool:
        currency_prices = plan.prices.get(currency)
        if not currency_prices:
            return False

        if duration in currency_prices:
            return True

        return any(
            available_duration in currency_prices
            for available_duration in plan.get_available_durations(self._durations)
        )

    def get_plan_changes(self, current_plan: Plan | str | None, duration: int, currency: str) -> list[Plan]:
        """Return public plans available for plan change (upgrades and downgrades)."""
        if isinstance(current_plan, str):
            current_plan = self.get_plan_by_code(current_plan)
        if not current_plan:
            return []

        current_public_plan = self.get_public_plan_equivalent(current_plan)
        current_offer_key = (
            current_public_plan.commercial_key
            if current_public_plan is not None
            else current_plan.commercial_key
        )

        result = []
        for plan in self.get_all_plans():
            if plan.commercial_key == current_offer_key:
                continue
            if not self._is_plan_available_for_currency(plan, currency, duration):
                continue
            result.append(plan)
        return result

    def get_all_plans(self, *, prefer_additional_profile: bool = False) -> list[Plan]:
        public_plans = list(self._public_plans_by_offer_key.values())
        return sorted(
            public_plans,
            key=lambda plan: self._public_plan_sort_key(
                plan,
                prefer_additional_profile=prefer_additional_profile,
            ),
        )

    def get_durations(self) -> list[int]:
        return self._durations
