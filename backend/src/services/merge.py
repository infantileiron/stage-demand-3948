"""Merge the completed forecast detail of several venues sharing one guide pool.

Sources are single-venue plans whose forecast run has completed. The source
plans, runs and scenarios are read-only here: the merged roster is a new,
separately persisted record, so the original forecast and every single-venue
plan stay untouched.

Accounting per day:
  demand (需求)     = sum of each venue's original guide suggestion
  allocated (实配)  = whole guides actually assigned from the shared pool
  gap (缺口)        = demand - allocated, in guides
  unused (闲置)     = daily capacity - allocated, in guides
  uncovered (人)    = people still above the 90% interval upper bound
Both balances are checked: allocated + gap == demand and allocated + unused ==
daily capacity, per day and on the totals row.
"""
import csv
import io
from datetime import date, timedelta
from fastapi import HTTPException
from src.constants.enums import RunStatus
from src.services.allocation import allocate, uncovered, venue_sort_key
from src.utils.database import insert_row, get_row, list_rows

MIN_USHERS = 2


def _run_capacity(run):
    capacity = (run.get("result") or {}).get("capacity")
    if not isinstance(capacity, (int, float)) or capacity <= 0:
        raise ValueError("来源运行缺少场馆容量")
    return capacity


def _checked_sources(plan_ids):
    if len(set(plan_ids)) != len(plan_ids):
        raise ValueError("同一份编排不能重复选择，请移除重复来源")
    sources = []
    for ident in plan_ids:
        plan = get_row("plans", ident)
        run = get_row("runs", plan["run_id"])
        if run["status"] != RunStatus.COMPLETED.value or not run.get("result"):
            raise ValueError(f"编排「{plan['name']}」的预演尚未完成，不能合并")
        scenario = get_row("scenarios", run["scenario_id"])
        if scenario["venue"] != plan["venue"]:
            raise ValueError(f"编排「{plan['name']}」的场馆与来源预演不一致")
        sources.append({"plan": plan, "run": run, "scenario": scenario})
    venues = [item["plan"]["venue"] for item in sources]
    if len(set(venues)) != len(venues):
        duplicated = next(venue for venue in venues if venues.count(venue) > 1)
        raise ValueError(f"「{duplicated}」选择了多份编排，同一场馆只能有一份")
    return sources


def _days_of(plan):
    days = sorted(plan["days"], key=lambda day: day["date"])
    if not days:
        raise ValueError(f"编排「{plan['name']}」没有预演日期")
    try:
        dates = [date.fromisoformat(day["date"]) for day in days]
    except (TypeError, ValueError):
        raise ValueError(f"编排「{plan['name']}」的日期格式不正确")
    if any(later - earlier != timedelta(days=1) for earlier, later in zip(dates, dates[1:])):
        raise ValueError(f"编排「{plan['name']}」的预演日期不连续，请补齐后重新生成")
    return days


def _aligned_days(sources):
    spans = {item["plan"]["venue"]: _days_of(item["plan"]) for item in sources}
    first = min(date.fromisoformat(days[0]["date"]) for days in spans.values())
    last = max(date.fromisoformat(days[-1]["date"]) for days in spans.values())
    expected = (last - first).days + 1
    if any(len(days) != expected for days in spans.values()):
        raise ValueError("所选编排的预演日期范围必须完全一致，不能合并")
    return sorted({day["date"] for days in spans.values() for day in days})


def list_merges():
    return list_rows("merges")


def create(body):
    try:
        return _create(body)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


def _create(body):
    sources = _checked_sources(body.plan_ids)
    dates = _aligned_days(sources)
    ranked = sorted(sources, key=lambda item: venue_sort_key(item["plan"]["venue"]))
    capacity = int(body.daily_capacity)
    if capacity < MIN_USHERS * len(ranked):
        raise ValueError(f"每日人力容量{capacity}人不足以满足每厅保底{MIN_USHERS}人（至少需{MIN_USHERS * len(ranked)}人）")

    merged_days = []
    totals = {key: 0 for key in ("demand", "allocated", "gap", "unused", "uncovered")}
    reconciled = True
    for day_date in dates:
        rows = []
        for item in ranked:
            plan = item["plan"]
            day = next((entry for entry in plan["days"] if entry["date"] == day_date), None)
            if day is None:
                raise ValueError(f"「{plan['venue']}」缺少{day_date}的预演，请选择同区间编排")
            if day["lower"] > day["upper"]:
                raise ValueError(f"「{plan['venue']}」{day_date}的预演区间上下界颠倒")
            if int(day["ushers"]) < MIN_USHERS:
                raise ValueError(f"「{plan['venue']}」{day_date}的原建议少于每厅保底{MIN_USHERS}名")
            rows.append({"venue": plan["venue"], "plan_id": plan["id"],
                "run_id": item["run"]["id"],
                "prediction": day["prediction"], "lower": day["lower"], "upper": day["upper"],
                "demand": int(day["ushers"]),
                "people_per_usher": int(item["scenario"]["people_per_usher"])})
        assigned = allocate([row["upper"] for row in rows],
            [row["people_per_usher"] for row in rows], [row["demand"] for row in rows], capacity)
        for row, guides in zip(rows, assigned):
            # 需求=该厅原建议；实配=从共享池实发；缺口=需求-实配。
            row["allocated"] = guides
            row["gap"] = row["demand"] - guides
            row["uncovered"] = uncovered(row["upper"], row["people_per_usher"], guides)
        day = {"date": day_date, "venues": rows,
            "demand": sum(row["demand"] for row in rows),
            "allocated": sum(row["allocated"] for row in rows),
            "capacity": capacity,
            "uncovered": round(sum(row["uncovered"] for row in rows), 1),
            "uncovered_max": round(max(row["uncovered"] for row in rows), 1)}
        day["gap"] = day["demand"] - day["allocated"]
        day["unused"] = capacity - day["allocated"]
        day["checks"] = {
            "floor_met": all(row["allocated"] >= MIN_USHERS for row in rows),
            "within_capacity": day["allocated"] <= capacity,
            "within_suggestion": all(row["allocated"] <= row["demand"] for row in rows),
            "gap_balances": day["allocated"] + day["gap"] == day["demand"],
            "unused_balances": day["allocated"] + day["unused"] == capacity,
            "venue_demand_matches": day["demand"] == sum(row["demand"] for row in rows),
            "venue_gap_matches": day["gap"] == sum(row["gap"] for row in rows),
        }
        reconciled = reconciled and all(day["checks"].values())
        for key in totals:
            totals[key] += day[key]
        merged_days.append(day)
    totals["uncovered"] = round(totals["uncovered"], 1)
    totals["all_reconciled"] = reconciled

    roster = {"name": body.name, "plan_ids": [item["plan"]["id"] for item in sources],
        "venues": [item["plan"]["venue"] for item in ranked],
        "date_range": {"first": dates[0], "last": dates[-1]},
        "daily_capacity": capacity, "days": merged_days, "totals": totals,
        "reconciled": reconciled,
        "rules": {"min_per_venue": MIN_USHERS,
            "objective": "最小化单日单厅最大未覆盖人数（人），同分优先场馆顺序",
            "allocation": "按90%区间上界÷每人承载数取整；不超过每日总额与单厅原建议",
            "gap": "需求 - 实配（名）；实配 + 缺口 = 需求",
            "unused": "每日容量 - 实配（名）；实配 + 闲置 = 每日容量",
            "uncovered": "区间上界 - 实配×每人承载数（不小于0，人）"},
        "sources": [{"venue": item["plan"]["venue"], "plan_id": item["plan"]["id"],
            "run_id": item["run"]["id"], "capacity": _run_capacity(item["run"])} for item in ranked]}
    return insert_row("merges", body.name, roster)


def export(ident):
    roster = get_row("merges", ident)
    stream = io.StringIO(); stream.write("﻿")
    writer = csv.writer(stream)
    writer.writerow(["日期", "场馆", "预测人数", "90%下界", "90%上界", "每名承载人数",
        "需求（名）", "实配（名）", "缺口（名）", "闲置（名）", "未覆盖人数"])
    for day in roster["days"]:
        for index, row in enumerate(day["venues"]):
            writer.writerow([day["date"], row["venue"], row["prediction"], row["lower"], row["upper"],
                row["people_per_usher"], row["demand"], row["allocated"], row["gap"],
                day["unused"] if index == 0 else "", row["uncovered"]])
        writer.writerow([day["date"], "合计", "", "", "", "", day["demand"], day["allocated"],
            day["gap"], day["unused"], day["uncovered"]])
    totals = roster["totals"]
    writer.writerow(["总计", "", "", "", "", "", totals["demand"], totals["allocated"],
        totals["gap"], totals["unused"], totals["uncovered"]])
    return stream.getvalue()
