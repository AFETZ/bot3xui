import json

from app.bot.services import plan as plan_module


def test_plan_service_loads_repo_fallback_and_hidden_upgrade_plans(tmp_path, monkeypatch):
    plans_file = tmp_path / "plans.json"
    plans_file.write_text(
        json.dumps(
            {
                "durations": [30],
                "plans": [
                    {
                        "code": "p3",
                        "devices": 3,
                        "title": "3 устройства",
                        "prices": {"RUB": {"30": 349}},
                    },
                    {
                        "code": "p3a",
                        "devices": 3,
                        "title": "3 устройства + доп. профиль",
                        "is_public": False,
                        "includes_additional_profile": True,
                        "upgrade_from": "p3",
                        "prices": {"RUB": {"30": 498}},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(plan_module, "DEFAULT_PLANS_DIR", tmp_path / "app" / "data" / "plans.json")
    monkeypatch.setattr(plan_module, "BASE_DIR", tmp_path / "app")

    service = plan_module.PlanService()

    assert service.get_plan(3).code == "p3"
    assert service.get_plan_by_code("p3a").includes_additional_profile is True
    assert service.get_upgrade_plan("p3").code == "p3a"
    assert [plan.code for plan in service.get_all_plans()] == ["p3"]
