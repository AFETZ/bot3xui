import json
import logging
import os
import tempfile
from pathlib import Path

from app.bot.models import Plan
from app.bot.utils.navigation import NavSubscription
from app.config import BASE_DIR, DEFAULT_PLANS_DIR

logger = logging.getLogger(__name__)

DEFAULT_PAYMENT_ORDER = [
    NavSubscription.PAY_TELEGRAM_STARS.value,
    NavSubscription.PAY_CRYPTOMUS.value,
    NavSubscription.PAY_HELEKET.value,
    NavSubscription.PAY_YOOKASSA.value,
    NavSubscription.PAY_YOOMONEY.value,
]


class PlanService:
    def __init__(self) -> None:
        self.file_path = self._resolve_file_path().resolve()
        self.reload()

    def reload(self) -> None:
        try:
            with self.file_path.open("r", encoding="utf-8") as f:
                self.data = json.load(f)
            logger.info(f"Loaded plans data from '{self.file_path}'.")
        except json.JSONDecodeError:
            logger.error(f"Failed to parse file '{self.file_path}'. Invalid JSON format.")
            raise ValueError(f"File '{self.file_path}' is not a valid JSON file.")

        if "plans" not in self.data or not isinstance(self.data["plans"], list):
            logger.error(f"'plans' key is missing or not a list in '{self.file_path}'.")
            raise ValueError(f"'plans' key is missing or not a list in '{self.file_path}'.")

        if "durations" not in self.data or not isinstance(self.data["durations"], list):
            logger.error(f"'durations' key is missing or not a list in '{self.file_path}'.")
            raise ValueError(f"'durations' key is missing or not a list in '{self.file_path}'.")

        self.data.setdefault("payment_order", DEFAULT_PAYMENT_ORDER.copy())
        self._rebuild_indexes()
        logger.info("Plans loaded successfully.")

    def _rebuild_indexes(self) -> None:
        self._plans: list[Plan] = [Plan.from_dict(plan) for plan in self.data["plans"]]
        self._plans_by_code: dict[str, Plan] = {plan.code: plan for plan in self._plans}
        self._durations: list[int] = self.data["durations"]
        self._public_plans_by_offer_key: dict[tuple[int, bool], Plan] = {}
        for plan in self._plans:
            if not plan.is_public:
                continue
            self._public_plans_by_offer_key.setdefault(plan.commercial_key, plan)

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

    def _save(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.file_path.name}.",
            suffix=".tmp",
            dir=self.file_path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
                f.write("\n")
            os.replace(tmp_name, self.file_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    @staticmethod
    def parse_plan_json(raw_json: str) -> Plan:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as exception:
            raise ValueError(f"Invalid JSON: {exception}") from exception

        if not isinstance(payload, dict):
            raise ValueError("Plan JSON must be an object.")

        return Plan.from_dict(payload)

    def _validate_unique_code(self, plan: Plan, *, previous_code: str | None = None) -> None:
        existing = self._plans_by_code.get(plan.code)
        if existing and plan.code != previous_code:
            raise ValueError(f"Plan code '{plan.code}' already exists.")

    def get_all_plan_records(self) -> list[Plan]:
        return list(self._plans)

    def add_plan(self, plan: Plan) -> None:
        self._validate_unique_code(plan)
        self.data["plans"].append(plan.to_dict())
        self._save()
        self._rebuild_indexes()

    def update_plan(self, previous_code: str, plan: Plan) -> None:
        self._validate_unique_code(plan, previous_code=previous_code)
        for index, current in enumerate(self._plans):
            if current.code == previous_code:
                self.data["plans"][index] = plan.to_dict()
                self._save()
                self._rebuild_indexes()
                return
        raise ValueError(f"Plan code '{previous_code}' was not found.")

    def delete_plan(self, code: str) -> None:
        for index, plan in enumerate(self._plans):
            if plan.code == code:
                del self.data["plans"][index]
                self._save()
                self._rebuild_indexes()
                return
        raise ValueError(f"Plan code '{code}' was not found.")

    def get_payment_order(self) -> list[str]:
        order = self.data.get("payment_order")
        if not isinstance(order, list):
            return DEFAULT_PAYMENT_ORDER.copy()

        known = set(DEFAULT_PAYMENT_ORDER)
        cleaned = [str(item) for item in order if str(item) in known]
        for callback in DEFAULT_PAYMENT_ORDER:
            if callback not in cleaned:
                cleaned.append(callback)
        return cleaned

    def move_payment_method(self, callback: str, direction: int) -> list[str]:
        order = self.get_payment_order()
        if callback not in order:
            raise ValueError(f"Payment method '{callback}' is unknown.")

        index = order.index(callback)
        new_index = max(0, min(len(order) - 1, index + direction))
        if index != new_index:
            order[index], order[new_index] = order[new_index], order[index]

        self.data["payment_order"] = order
        self._save()
        return order

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
