from __future__ import annotations

from typing import Any

from diffgr.impact import build_impact_report
from diffgr.review_rebase import rebase_review_state
from diffgr.review_state import (
    apply_review_state,
    extract_review_state,
    iter_review_state_diff_rows,
    preview_review_state_selection,
    summarize_group_brief_record,
    summarize_merge_result,
    summarize_review_state,
)


def summarize_impact_report(report: dict[str, Any]) -> dict[str, Any]:
    groups = report.get("groups", []) if isinstance(report.get("groups"), list) else []
    impacted_groups: list[dict[str, Any]] = []
    unchanged_groups: list[dict[str, Any]] = []
    for item in groups:
        if not isinstance(item, dict):
            continue
        payload = {
            "groupId": str(item.get("id", "")),
            "name": str(item.get("name", "")),
            "action": str(item.get("action", "")),
            "changed": int(item.get("changed", 0) or 0),
            "unchanged": int(item.get("unchanged", 0) or 0),
            "new": int(item.get("new", 0) or 0),
            "removed": int(item.get("removed", 0) or 0),
        }
        if payload["action"] == "review":
            impacted_groups.append(payload)
        else:
            unchanged_groups.append(payload)
    return {
        "grouping": str(report.get("grouping", "")),
        "impactedGroupCount": len(impacted_groups),
        "unchangedGroupCount": len(unchanged_groups),
        "impactedGroupIds": [item["groupId"] for item in impacted_groups],
        "unchangedGroupIds": [item["groupId"] for item in unchanged_groups],
        "impactedGroups": impacted_groups,
        "unchangedGroups": unchanged_groups,
        "newOnlyChunkIds": list(report.get("newOnlyChunkIds", []) or []),
        "oldOnlyChunkIds": list(report.get("oldOnlyChunkIds", []) or []),
    }


def summarize_rebase_warnings(warnings: list[str], *, unmapped_new_chunks: int = 0) -> dict[str, Any]:
    kinds = {
        "statusConflict": 0,
        "chunkCommentConflict": 0,
        "groupBriefConflict": 0,
        "invalidReviewRecord": 0,
        "invalidGroupBriefRecord": 0,
        "rebaseUnmappedChunk": 0,
        "rebaseWeakMatch": 0,
        "other": 0,
    }
    for warning in warnings:
        text = str(warning)
        if "status conflict on chunk" in text:
            kinds["statusConflict"] += 1
        elif "chunk comment conflict on chunk" in text:
            kinds["chunkCommentConflict"] += 1
        elif "group brief conflict on" in text:
            kinds["groupBriefConflict"] += 1
        elif "review record must be object" in text:
            kinds["invalidReviewRecord"] += 1
        elif "group brief record must be object" in text:
            kinds["invalidGroupBriefRecord"] += 1
        elif text.startswith("Ambiguous "):
            kinds["rebaseWeakMatch"] += 1
        else:
            kinds["other"] += 1
    if unmapped_new_chunks > 0:
        kinds["rebaseUnmappedChunk"] = int(unmapped_new_chunks)
    return {
        "total": len(warnings) + int(unmapped_new_chunks),
        "kinds": kinds,
        "raw": [str(item) for item in warnings],
    }


def _selection_plan_sort_key(token: str) -> tuple[int, str]:
    section = str(token).split(":", 1)[0]
    order = {
        "groupBriefs": 1,
        "reviews": 2,
        "analysisState": 3,
        "threadState": 4,
        "threadState.__files": 4,
    }
    return (order.get(section, 99), str(token))


def build_impact_selection_plans(preview: dict[str, Any]) -> dict[str, Any]:
    impact_summary = preview.get("impactSummary", {}) if isinstance(preview.get("impactSummary"), dict) else {}
    impact_report = preview.get("impactReport", {}) if isinstance(preview.get("impactReport"), dict) else {}
    merge_summary = preview.get("mergeSummary", {}) if isinstance(preview.get("mergeSummary"), dict) else {}
    diff = merge_summary.get("diff", {}) if isinstance(merge_summary.get("diff"), dict) else {}
    impacted_group_ids = {str(item) for item in impact_summary.get("impactedGroupIds", []) or [] if str(item)}
    affected_briefs = preview.get("affectedBriefs", []) if isinstance(preview.get("affectedBriefs"), list) else []
    handoff_group_ids = {
        str(item.get("groupId", ""))
        for item in affected_briefs
        if isinstance(item, dict) and str(item.get("groupId", ""))
    }
    impacted_review_keys: set[str] = set()
    for item in (impact_report.get("groups", []) if isinstance(impact_report.get("groups"), list) else []):
        if not isinstance(item, dict) or str(item.get("action", "")) != "review":
            continue
        for key_name in ("changedChunkIds", "removedChunkIds", "newChunkIds"):
            values = item.get(key_name, [])
            if not isinstance(values, list):
                continue
            impacted_review_keys.update(str(value) for value in values if str(value))

    handoff_tokens: list[str] = sorted(
        {f"groupBriefs:{group_id}" for group_id in handoff_group_ids},
        key=_selection_plan_sort_key,
    )
    review_tokens: list[str] = []
    ui_tokens: list[str] = []
    for row in iter_review_state_diff_rows(diff):
        if not isinstance(row, dict):
            continue
        section = str(row.get("section", "")).strip()
        key = str(row.get("key", "")).strip()
        token = str(row.get("selectionToken", "")).strip()
        if not token:
            continue
        if section == "groupBriefs" and key in impacted_group_ids and token not in handoff_tokens:
            handoff_tokens.append(token)
        elif section == "reviews" and key in impacted_review_keys and token not in review_tokens:
            review_tokens.append(token)
        elif section in {"analysisState", "threadState"} and token not in ui_tokens:
            ui_tokens.append(token)

    handoff_tokens = sorted(handoff_tokens, key=_selection_plan_sort_key)
    review_tokens = sorted(review_tokens, key=_selection_plan_sort_key)
    ui_tokens = sorted(ui_tokens, key=_selection_plan_sort_key)
    all_tokens = sorted({*handoff_tokens, *review_tokens, *ui_tokens}, key=_selection_plan_sort_key)
    return {
        "handoffs": {"tokens": handoff_tokens, "count": len(handoff_tokens)},
        "reviews": {"tokens": review_tokens, "count": len(review_tokens)},
        "ui": {"tokens": ui_tokens, "count": len(ui_tokens)},
        "all": {"tokens": all_tokens, "count": len(all_tokens)},
    }


def build_impact_preview_report(
    preview: dict[str, Any],
    *,
    old_label: str,
    new_label: str,
    state_label: str,
) -> dict[str, Any]:
    impact_summary = preview.get("impactSummary", {}) if isinstance(preview.get("impactSummary"), dict) else {}
    merge_summary = preview.get("mergeSummary", {}) if isinstance(preview.get("mergeSummary"), dict) else {}
    state_diff = merge_summary.get("diff", {}) if isinstance(merge_summary.get("diff"), dict) else {}
    group_brief_changes = (
        merge_summary.get("briefChanges", []) if isinstance(merge_summary.get("briefChanges"), list) else []
    )
    rebase_summary = preview.get("rebaseSummary", {}) if isinstance(preview.get("rebaseSummary"), dict) else {}
    warning_summary = preview.get("warningSummary", {}) if isinstance(preview.get("warningSummary"), dict) else {}
    selection_plans = preview.get("selectionPlans", {})
    if not isinstance(selection_plans, dict) or not selection_plans:
        selection_plans = build_impact_selection_plans(preview)
    return {
        "title": f"Impact Preview: {old_label} -> {new_label} using {state_label}",
        "sourceLabel": f"{old_label} -> {new_label} using {state_label}",
        "changeSummary": {
            "carriedReviews": int(rebase_summary.get("carriedReviews", 0) or 0),
            "changedToNeedsReReview": int(rebase_summary.get("changedToNeedsReReview", 0) or 0),
            "unmappedNewChunks": int(rebase_summary.get("unmappedNewChunks", 0) or 0),
        },
        "impactSummary": impact_summary,
        "impactedGroups": impact_summary.get("impactedGroups", []) if isinstance(impact_summary.get("impactedGroups"), list) else [],
        "unchangedGroups": impact_summary.get("unchangedGroups", []) if isinstance(impact_summary.get("unchangedGroups"), list) else [],
        "affectedBriefs": preview.get("affectedBriefs", []) if isinstance(preview.get("affectedBriefs"), list) else [],
        "warningSummary": warning_summary,
        "groupBriefChanges": group_brief_changes,
        "stateDiff": state_diff,
        "rebaseSummary": rebase_summary,
        "selectionPlans": selection_plans,
    }


def preview_impact_apply(
    *,
    old_doc: dict[str, Any],
    new_doc: dict[str, Any],
    state: dict[str, Any],
    plan: str,
    old_label: str | None = None,
    new_label: str | None = None,
    state_label: str | None = None,
) -> dict[str, Any]:
    preview = preview_impact_merge(old_doc=old_doc, new_doc=new_doc, state=state)
    report = build_impact_preview_report(
        preview,
        old_label=str(old_label or old_doc.get("meta", {}).get("title", "old")),
        new_label=str(new_label or new_doc.get("meta", {}).get("title", "new")),
        state_label=str(state_label or "state"),
    )
    selection_plans = report.get("selectionPlans", {}) if isinstance(report.get("selectionPlans"), dict) else {}
    plan_payload = selection_plans.get(plan, {}) if isinstance(selection_plans.get(plan), dict) else {}
    selection_tokens = [str(item) for item in plan_payload.get("tokens", []) if str(item)]
    if selection_tokens:
        selection_preview = preview_review_state_selection(state, preview["rebasedState"], selection_tokens)
        next_state = selection_preview["nextState"]
    else:
        selection_preview = None
        next_state = state
    return {
        "planName": plan,
        "selectionTokens": selection_tokens,
        "selectionPreview": selection_preview,
        "nextState": next_state,
        "sourceLabel": report.get("sourceLabel", ""),
        "impactPreview": preview,
        "impactReport": report,
    }


def format_impact_preview_text(
    preview: dict[str, Any],
    *,
    old_label: str,
    new_label: str,
    state_label: str,
) -> str:
    report = build_impact_preview_report(
        preview,
        old_label=old_label,
        new_label=new_label,
        state_label=state_label,
    )
    impact_summary = report["impactSummary"]
    change_summary = report.get("changeSummary", {}) if isinstance(report.get("changeSummary"), dict) else {}
    warning_summary = report["warningSummary"]
    warning_kinds = warning_summary.get("kinds", {}) if isinstance(warning_summary.get("kinds"), dict) else {}
    lines = [report["title"]]
    lines.append(f"Source: {report.get('sourceLabel', '')}")
    lines.append(
        "Change Summary: carriedReviews={carried} changedToNeedsReReview={changed} unmappedNewChunks={unmapped}".format(
            carried=change_summary.get("carriedReviews", 0),
            changed=change_summary.get("changedToNeedsReReview", 0),
            unmapped=change_summary.get("unmappedNewChunks", 0),
        )
    )
    lines.append(
        "Impact: changed groups={changed} unchanged groups={unchanged} newOnly={new_only} oldOnly={old_only}".format(
            changed=impact_summary.get("impactedGroupCount", 0),
            unchanged=impact_summary.get("unchangedGroupCount", 0),
            new_only=len(impact_summary.get("newOnlyChunkIds", []) or []),
            old_only=len(impact_summary.get("oldOnlyChunkIds", []) or []),
        )
    )
    lines.append(
        "Warnings: total={total} status={status} chunkComment={chunk} brief={brief} invalid={invalid_total} rebaseWeak={weak} rebaseUnmapped={unmapped}".format(
            total=warning_summary.get("total", 0),
            status=warning_kinds.get("statusConflict", 0),
            chunk=warning_kinds.get("chunkCommentConflict", 0),
            brief=warning_kinds.get("groupBriefConflict", 0),
            invalid_total=int(warning_kinds.get("invalidReviewRecord", 0))
            + int(warning_kinds.get("invalidGroupBriefRecord", 0)),
            weak=warning_kinds.get("rebaseWeakMatch", 0),
            unmapped=warning_kinds.get("rebaseUnmappedChunk", 0),
        )
    )
    group_brief_changes = report.get("groupBriefChanges", []) if isinstance(report.get("groupBriefChanges"), list) else []
    if group_brief_changes:
        lines.append("Group Brief Changes:")
        for item in group_brief_changes:
            if not isinstance(item, dict):
                continue
            before = item.get("before", {}) if isinstance(item.get("before"), dict) else {}
            after = item.get("after", {}) if isinstance(item.get("after"), dict) else {}
            lines.append(
                "  - {group_id}: {kind} status={before_status}->{after_status} summary={before_summary}->{after_summary}".format(
                    group_id=item.get("groupId", ""),
                    kind=item.get("changeKind", ""),
                    before_status=before.get("status", "") or "-",
                    after_status=after.get("status", "") or "-",
                    before_summary=before.get("summary", "") or "-",
                    after_summary=after.get("summary", "") or "-",
                )
            )
    impacted_groups = report["impactedGroups"]
    if impacted_groups:
        lines.append("Impacted Groups:")
        for item in impacted_groups:
            if not isinstance(item, dict):
                continue
            lines.append(
                "  - {group_id} {name}: changed={changed} new={new} removed={removed}".format(
                    group_id=item.get("groupId", ""),
                    name=item.get("name", ""),
                    changed=item.get("changed", 0),
                    new=item.get("new", 0),
                    removed=item.get("removed", 0),
                )
            )
    affected_briefs = report["affectedBriefs"]
    if affected_briefs:
        lines.append("Affected Briefs:")
        for item in affected_briefs:
            if not isinstance(item, dict):
                continue
            lines.append(
                "  - {group_id}: status={status} summary={summary} focus={focus} tests={tests} questions={questions}".format(
                    group_id=item.get("groupId", ""),
                    status=item.get("status", "") or "-",
                    summary=item.get("summary", "") or "-",
                    focus=item.get("focusPointsCount", 0),
                    tests=item.get("testEvidenceCount", 0),
                    questions=item.get("questionsCount", 0),
                )
            )
    selection_plans = report.get("selectionPlans", {}) if isinstance(report.get("selectionPlans"), dict) else {}
    if selection_plans:
        lines.append("Selection Plans:")
        for plan_name in ("handoffs", "reviews", "ui", "all"):
            plan = selection_plans.get(plan_name, {}) if isinstance(selection_plans.get(plan_name), dict) else {}
            tokens = [str(item) for item in plan.get("tokens", []) if str(item)]
            lines.append(f"  - {plan_name}: count={plan.get('count', len(tokens))}")
            for token in tokens:
                lines.append(f"    {token}")
    diff = report["stateDiff"]
    if isinstance(diff, dict):
        lines.append("State Diff:")
        for section_name in ("reviews", "groupBriefs", "analysisState", "threadState"):
            section = diff.get(section_name, {}) if isinstance(diff.get(section_name), dict) else {}
            lines.append(
                f"  {section_name}: added={section.get('addedCount', 0)} removed={section.get('removedCount', 0)} changed={section.get('changedCount', 0)} unchanged={section.get('unchangedCount', 0)}"
            )
    return "\n".join(lines)


def preview_impact_merge(
    *,
    old_doc: dict[str, Any],
    new_doc: dict[str, Any],
    state: dict[str, Any],
    preserve_groups: bool = True,
    carry_line_comments: bool = True,
    similarity_threshold: float = 0.86,
    impact_grouping: str = "old",
) -> dict[str, Any]:
    old_doc_with_state = apply_review_state(old_doc, state)
    rebased_doc, rebase_summary, rebase_warnings = rebase_review_state(
        old_doc=old_doc_with_state,
        new_doc=new_doc,
        preserve_groups=preserve_groups,
        carry_line_comments=carry_line_comments,
        similarity_threshold=similarity_threshold,
    )
    rebased_state = extract_review_state(rebased_doc)
    impact_report = build_impact_report(
        old_doc=old_doc,
        new_doc=new_doc,
        grouping=impact_grouping,
        similarity_threshold=similarity_threshold,
    )
    impact_summary = summarize_impact_report(impact_report)
    merge_summary = summarize_merge_result(
        state,
        rebased_state,
        rebase_warnings,
        incoming_states=[],
        applied=rebase_summary.carried_reviews,
    )
    affected_briefs: list[dict[str, Any]] = []
    for group_id in impact_summary["impactedGroupIds"]:
        brief = rebased_state.get("groupBriefs", {}).get(group_id, {})
        brief_summary = summarize_group_brief_record(brief)
        if any(brief_summary.values()):
            affected_briefs.append({"groupId": group_id, **brief_summary})
    warning_summary = summarize_rebase_warnings(
        rebase_warnings,
        unmapped_new_chunks=rebase_summary.unmapped_new_chunks,
    )
    selection_plans = build_impact_selection_plans(
        {
            "impactReport": impact_report,
            "impactSummary": impact_summary,
            "mergeSummary": merge_summary,
            "affectedBriefs": affected_briefs,
        }
    )
    return {
        "impactReport": impact_report,
        "impactSummary": impact_summary,
        "rebasedState": rebased_state,
        "rebasedStateSummary": summarize_review_state(rebased_state),
        "mergeSummary": merge_summary,
        "warningSummary": warning_summary,
        "rebaseSummary": {
            "matchedStrong": rebase_summary.matched_strong,
            "matchedStable": rebase_summary.matched_stable,
            "matchedDelta": rebase_summary.matched_delta,
            "matchedSimilar": rebase_summary.matched_similar,
            "carriedReviews": rebase_summary.carried_reviews,
            "carriedReviewed": rebase_summary.carried_reviewed,
            "changedToNeedsReReview": rebase_summary.changed_to_needs_rereview,
            "unmappedNewChunks": rebase_summary.unmapped_new_chunks,
            "warnings": list(rebase_warnings),
        },
        "affectedBriefs": affected_briefs,
        "selectionPlans": selection_plans,
    }
