from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from diffgr.generator import canonical_json as _canonical_json
from diffgr.group_brief_utils import (
    GROUP_BRIEF_STATUS_PRECEDENCE,
    merge_group_brief_records as _merge_group_brief_records,
    normalize_group_brief_status as _normalize_group_brief_status,
    summarize_group_brief_record,
)
from diffgr.review_utils import (
    REVIEW_STATUS_PRECEDENCE,
    line_comment_identity as _line_comment_identity,
    merge_review_records as _merge_review_records,
    normalize_comment as _normalize_comment,
    normalize_review_status as _normalize_review_status,
    normalized_line_comments as _normalized_line_comments,
)
from diffgr.viewer_core import load_json, validate_document, write_json

STATE_KEYS = ("reviews", "groupBriefs", "analysisState", "threadState")
STATE_SELECTION_SECTIONS = ("reviews", "groupBriefs", "analysisState", "threadState", "threadState.__files")
STATE_DIFF_SECTIONS = ("reviews", "groupBriefs", "analysisState", "threadState")

def empty_review_state() -> dict[str, dict[str, Any]]:
    return {key: {} for key in STATE_KEYS}


def normalize_review_state_payload(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise RuntimeError("State payload must be a JSON object.")
    if "state" in payload:
        payload = payload["state"]
        if not isinstance(payload, dict):
            raise RuntimeError("`state` must be a JSON object.")

    state = empty_review_state()
    if not any(key in payload for key in STATE_KEYS):
        raise RuntimeError("State payload must include one or more of: reviews, groupBriefs, analysisState, threadState.")
    for key in STATE_KEYS:
        candidate = payload.get(key, {})
        if not isinstance(candidate, dict):
            raise RuntimeError(f"`{key}` must be a JSON object.")
        state[key] = copy.deepcopy(candidate)
    return state


def extract_review_state(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    state = empty_review_state()
    for key in STATE_KEYS:
        candidate = doc.get(key, {})
        if isinstance(candidate, dict):
            state[key] = copy.deepcopy(candidate)
    return state


def apply_review_state(doc: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_review_state_payload(state)
    out = copy.deepcopy(doc)
    for key in STATE_KEYS:
        candidate = normalized.get(key, {})
        if candidate or key == "reviews":
            out[key] = copy.deepcopy(candidate)
        else:
            out.pop(key, None)
    return out


def load_review_state(path: Path) -> dict[str, dict[str, Any]]:
    return normalize_review_state_payload(load_json(path))


def review_state_fingerprint(state: dict[str, Any]) -> str:
    normalized = normalize_review_state_payload(state)
    return _canonical_json(normalized)


def save_review_state(path: Path, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized = normalize_review_state_payload(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, normalized)
    return normalized


def load_diffgr_document(path: Path) -> dict[str, Any]:
    doc = load_json(path)
    validate_document(doc)
    return doc


def merge_review_states(
    base_state: dict[str, Any],
    incoming_states: list[tuple[str, dict[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], list[str], int]:
    merged = normalize_review_state_payload(base_state)
    warnings: list[str] = []
    applied = 0

    for source_name, incoming_state in incoming_states:
        state = normalize_review_state_payload(incoming_state)

        for chunk_id, review_record in state["reviews"].items():
            chunk_id_str = str(chunk_id)
            if not isinstance(review_record, dict):
                warnings.append(f"{source_name}: review record must be object for chunk: {chunk_id_str}")
                continue
            base_record = merged["reviews"].get(chunk_id_str, {})
            if not isinstance(base_record, dict):
                base_record = {}
            merged["reviews"][chunk_id_str] = _merge_review_records(
                base_record,
                review_record,
                source_name=source_name,
                chunk_id=chunk_id_str,
                warnings=warnings,
            )
            applied += 1

        for group_id, brief_record in state["groupBriefs"].items():
            group_id_str = str(group_id)
            if not isinstance(brief_record, dict):
                warnings.append(f"{source_name}: group brief record must be object for group: {group_id_str}")
                continue
            base_record = merged["groupBriefs"].get(group_id_str, {})
            if not isinstance(base_record, dict):
                base_record = {}
            merged["groupBriefs"][group_id_str] = _merge_group_brief_records(
                base_record,
                brief_record,
                source_name=source_name,
                group_id=group_id_str,
                warnings=warnings,
            )

        for key, value in state["analysisState"].items():
            merged["analysisState"][key] = copy.deepcopy(value)

        for key, value in state["threadState"].items():
            if str(key) == "__files" and isinstance(value, dict):
                existing = merged["threadState"].get("__files", {})
                if not isinstance(existing, dict):
                    existing = {}
                for file_key, file_value in value.items():
                    existing[str(file_key)] = copy.deepcopy(file_value)
                merged["threadState"]["__files"] = existing
            else:
                merged["threadState"][str(key)] = copy.deepcopy(value)

    return merged, warnings, applied


def _state_entry_counts(state: dict[str, Any]) -> dict[str, int]:
    normalized = normalize_review_state_payload(state)
    thread_state = normalized["threadState"]
    file_state = thread_state.get("__files", {}) if isinstance(thread_state.get("__files"), dict) else {}
    return {
        "reviews": len(normalized["reviews"]),
        "groupBriefs": len(normalized["groupBriefs"]),
        "analysisState": len(normalized["analysisState"]),
        "threadState": sum(1 for key in thread_state if str(key) != "__files"),
        "threadStateFiles": len(file_state),
    }



def summarize_group_brief_changes(base_state: dict[str, Any], merged_state: dict[str, Any]) -> list[dict[str, Any]]:
    base = normalize_review_state_payload(base_state)
    merged = normalize_review_state_payload(merged_state)
    group_ids = sorted(set(base["groupBriefs"].keys()) | set(merged["groupBriefs"].keys()))
    changes: list[dict[str, Any]] = []
    for group_id in group_ids:
        before = summarize_group_brief_record(base["groupBriefs"].get(group_id, {}))
        after = summarize_group_brief_record(merged["groupBriefs"].get(group_id, {}))
        if _canonical_json(before) == _canonical_json(after):
            continue
        if group_id not in base["groupBriefs"]:
            change_kind = "added"
        elif group_id not in merged["groupBriefs"]:
            change_kind = "removed"
        else:
            change_kind = "changed"
        changes.append(
            {
                "groupId": str(group_id),
                "changeKind": change_kind,
                "before": before,
                "after": after,
            }
        )
    return changes


def summarize_incoming_state_inputs(incoming_states: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for source_name, incoming_state in incoming_states:
        counts = _state_entry_counts(incoming_state)
        summaries.append({"source": str(source_name), **counts})
    return summaries


def preview_merge_review_states(
    base_state: dict[str, Any],
    incoming_states: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    merged_state, warnings, applied = merge_review_states(base_state, incoming_states)
    return {
        "mergedState": merged_state,
        "warnings": warnings,
        "applied": applied,
        "summary": summarize_merge_result(base_state, merged_state, warnings, incoming_states=incoming_states, applied=applied),
    }


def build_merge_preview_report(preview: dict[str, Any], *, target_label: str) -> dict[str, Any]:
    summary = preview.get("summary", {}) if isinstance(preview.get("summary"), dict) else {}
    warnings = summary.get("warnings", {}) if isinstance(summary.get("warnings"), dict) else {}
    inputs = summary.get("inputs", []) if isinstance(summary.get("inputs"), list) else []
    group_brief_changes = summary.get("briefChanges", []) if isinstance(summary.get("briefChanges"), list) else []
    state_diff = summary.get("diff", {}) if isinstance(summary.get("diff"), dict) else {}
    return {
        "title": f"State Merge Preview: {target_label}",
        "sourceLabel": str(target_label),
        "changeSummary": {
            "inputCount": len(inputs),
            "appliedReviews": int(preview.get("applied", 0) or 0),
        },
        "warnings": warnings,
        "groupBriefChanges": group_brief_changes,
        "stateDiff": state_diff,
        "inputs": inputs,
    }


def format_merge_preview_text(preview: dict[str, Any], *, target_label: str) -> str:
    report = build_merge_preview_report(preview, target_label=target_label)
    change_summary = report.get("changeSummary", {}) if isinstance(report.get("changeSummary"), dict) else {}
    warnings = report.get("warnings", {}) if isinstance(report.get("warnings"), dict) else {}
    warning_kinds = warnings.get("kinds", {}) if isinstance(warnings.get("kinds"), dict) else {}
    lines = [str(report.get("title", ""))]
    lines.append(f"Source: {report.get('sourceLabel', '')}")
    lines.append(
        "Change Summary: inputs={inputs} applied={applied}".format(
            inputs=change_summary.get("inputCount", 0),
            applied=change_summary.get("appliedReviews", 0),
        )
    )
    lines.append(
        "Warnings: total={total} status={status} chunkComment={chunk} brief={brief} invalid={invalid_total}".format(
            total=warnings.get("total", 0),
            status=warning_kinds.get("statusConflict", 0),
            chunk=warning_kinds.get("chunkCommentConflict", 0),
            brief=warning_kinds.get("groupBriefConflict", 0),
            invalid_total=int(warning_kinds.get("invalidReviewRecord", 0))
            + int(warning_kinds.get("invalidGroupBriefRecord", 0)),
        )
    )
    brief_changes = report.get("groupBriefChanges", []) if isinstance(report.get("groupBriefChanges"), list) else []
    if brief_changes:
        lines.append("Group Brief Changes:")
        for item in brief_changes:
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
    diff = report.get("stateDiff", {})
    if isinstance(diff, dict):
        lines.append("State Diff:")
        for section_name in STATE_DIFF_SECTIONS:
            section = diff.get(section_name, {}) if isinstance(diff.get(section_name), dict) else {}
            lines.append(
                f"  {section_name}: added={section.get('addedCount', 0)} removed={section.get('removedCount', 0)} "
                f"changed={section.get('changedCount', 0)} unchanged={section.get('unchangedCount', 0)}"
            )
    return "\n".join(lines)


def _preview_value(value: Any, *, limit: int = 96) -> str:
    if isinstance(value, str):
        rendered = value
    else:
        rendered = _canonical_json(value)
    if len(rendered) <= limit:
        return rendered
    return rendered[: max(0, limit - 1)] + "…"


def _selection_token(section: str, key: str) -> str:
    return f"{section}:{key}"


def parse_review_state_selection(tokens: list[str]) -> dict[str, list[str]]:
    selection = {
        "reviews": [],
        "groupBriefs": [],
        "analysisState": [],
        "threadState": [],
        "threadState.__files": [],
    }
    seen: dict[str, set[str]] = {key: set() for key in selection}
    for raw in tokens:
        token = str(raw or "").strip()
        if not token:
            continue
        if ":" not in token:
            raise RuntimeError(f"Invalid selection token: {token}")
        section, values = token.split(":", 1)
        section = section.strip()
        if section not in selection:
            raise RuntimeError(f"Unknown selection section: {section}")
        keys = [item.strip() for item in values.split(",")]
        keys = [item for item in keys if item]
        if not keys:
            raise RuntimeError(f"Selection token must include one or more keys: {token}")
        for key in keys:
            if key in seen[section]:
                continue
            seen[section].add(key)
            selection[section].append(key)
    return selection


def _thread_state_file_map(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    raw = value.get("__files")
    if not isinstance(raw, dict):
        return {}
    return raw


def collect_review_state_selectable_keys(base_state: dict[str, Any], other_state: dict[str, Any]) -> dict[str, set[str]]:
    base = normalize_review_state_payload(base_state)
    other = normalize_review_state_payload(other_state)
    selectable = {
        "reviews": set(str(key) for key in set(base["reviews"].keys()) | set(other["reviews"].keys())),
        "groupBriefs": set(str(key) for key in set(base["groupBriefs"].keys()) | set(other["groupBriefs"].keys())),
        "analysisState": set(str(key) for key in set(base["analysisState"].keys()) | set(other["analysisState"].keys())),
        "threadState": set(),
        "threadState.__files": set(),
    }
    thread_keys = set(base["threadState"].keys()) | set(other["threadState"].keys())
    selectable["threadState"] = {str(key) for key in thread_keys if str(key) != "__files"}
    file_keys = set(_thread_state_file_map(base["threadState"]).keys()) | set(_thread_state_file_map(other["threadState"]).keys())
    selectable["threadState.__files"] = {str(key) for key in file_keys}
    return selectable


def validate_review_state_selection(
    base_state: dict[str, Any],
    other_state: dict[str, Any],
    selection_tokens: list[str],
) -> dict[str, list[str]]:
    selection = parse_review_state_selection(selection_tokens)
    selectable = collect_review_state_selectable_keys(base_state, other_state)
    for section, keys in selection.items():
        available = selectable.get(section, set())
        for key in keys:
            if key not in available:
                raise RuntimeError(f"Unknown selection key for {section}: {key}")
    return selection


def apply_review_state_selection(
    base_state: dict[str, Any],
    other_state: dict[str, Any],
    selection_tokens: list[str],
) -> tuple[dict[str, dict[str, Any]], int]:
    base = normalize_review_state_payload(base_state)
    other = normalize_review_state_payload(other_state)
    selection = validate_review_state_selection(base, other, selection_tokens)
    out = normalize_review_state_payload(base)
    applied = 0

    for section in ("reviews", "groupBriefs", "analysisState"):
        for key in selection[section]:
            if key in other[section]:
                out[section][key] = copy.deepcopy(other[section][key])
            else:
                out[section].pop(key, None)
            applied += 1

    for key in selection["threadState"]:
        if key in other["threadState"]:
            out["threadState"][key] = copy.deepcopy(other["threadState"][key])
        else:
            out["threadState"].pop(key, None)
        applied += 1

    if selection["threadState.__files"]:
        out_files = _thread_state_file_map(out["threadState"])
        other_files = _thread_state_file_map(other["threadState"])
        if not out_files and selection["threadState.__files"]:
            out["threadState"]["__files"] = out_files
        for key in selection["threadState.__files"]:
            if key in other_files:
                out_files[key] = copy.deepcopy(other_files[key])
            else:
                out_files.pop(key, None)
            applied += 1
        if not out_files:
            out["threadState"].pop("__files", None)
    return out, applied


def preview_review_state_selection(
    base_state: dict[str, Any],
    other_state: dict[str, Any],
    selection_tokens: list[str],
) -> dict[str, Any]:
    base = normalize_review_state_payload(base_state)
    other = normalize_review_state_payload(other_state)
    selection = validate_review_state_selection(base, other, selection_tokens)
    next_state, applied = apply_review_state_selection(base, other, selection_tokens)
    result_diff = diff_review_states(base, next_state)
    rows: list[dict[str, str | bool]] = []
    no_op_count = 0
    section_counts = {section: 0 for section in STATE_SELECTION_SECTIONS}

    def _append_row(section: str, key: str, token: str) -> None:
        nonlocal no_op_count
        base_present: bool
        other_present: bool
        base_value: Any
        other_value: Any
        if section == "threadState.__files":
            base_files = _thread_state_file_map(base["threadState"])
            other_files = _thread_state_file_map(other["threadState"])
            base_present = key in base_files
            other_present = key in other_files
            base_value = base_files.get(key)
            other_value = other_files.get(key)
        else:
            base_map = base["threadState"] if section == "threadState" else base[section]
            other_map = other["threadState"] if section == "threadState" else other[section]
            base_present = key in base_map
            other_present = key in other_map
            base_value = base_map.get(key)
            other_value = other_map.get(key)
        if not base_present and other_present:
            change_kind = "added"
            preview = _preview_value(other_value)
        elif base_present and not other_present:
            change_kind = "removed"
            preview = _preview_value(base_value)
        elif _canonical_json(base_value) != _canonical_json(other_value):
            change_kind = "changed"
            preview = f"{_preview_value(base_value)} -> {_preview_value(other_value)}"
        else:
            change_kind = "unchanged"
            preview = _preview_value(base_value)
            no_op_count += 1
        rows.append(
            {
                "section": section,
                "key": key,
                "selectionToken": token,
                "changeKind": change_kind,
                "preview": preview,
                "selectable": True,
            }
        )
        section_counts[section] += 1

    for section in STATE_SELECTION_SECTIONS:
        for key in selection[section]:
            _append_row(section, key, _selection_token(section, key))

    changed_sections = sum(
        1
        for section_name in STATE_DIFF_SECTIONS
        if int(result_diff.get(section_name, {}).get("addedCount", 0))
        or int(result_diff.get(section_name, {}).get("removedCount", 0))
        or int(result_diff.get(section_name, {}).get("changedCount", 0))
    )
    return {
        "selection": selection,
        "rows": rows,
        "summary": {
            "tokenCount": len([str(token).strip() for token in selection_tokens if str(token).strip()]),
            "selectedKeyCount": applied,
            "sectionCounts": section_counts,
            "noOpCount": no_op_count,
            "appliedCount": applied,
            "changedSectionCount": changed_sections,
        },
        "nextState": next_state,
        "resultDiff": result_diff,
    }


def diff_review_states(base_state: dict[str, Any], incoming_state: dict[str, Any]) -> dict[str, Any]:
    base = normalize_review_state_payload(base_state)
    incoming = normalize_review_state_payload(incoming_state)

    def diff_mapping(base_map: dict[str, Any], incoming_map: dict[str, Any], *, section_name: str) -> dict[str, Any]:
        added: list[str] = []
        removed: list[str] = []
        changed: list[str] = []
        unchanged: list[str] = []
        added_details: list[dict[str, str]] = []
        removed_details: list[dict[str, str]] = []
        changed_details: list[dict[str, str]] = []
        all_keys = sorted(set(base_map.keys()) | set(incoming_map.keys()))
        if section_name == "threadState":
            all_keys = [key for key in all_keys if str(key) != "__files"]
        for key in all_keys:
            if key not in base_map:
                key_str = str(key)
                added.append(key_str)
                added_details.append(
                    {
                        "key": key_str,
                        "preview": _preview_value(incoming_map[key]),
                        "selectionToken": _selection_token(section_name, key_str),
                    }
                )
            elif key not in incoming_map:
                key_str = str(key)
                removed.append(key_str)
                removed_details.append(
                    {
                        "key": key_str,
                        "preview": _preview_value(base_map[key]),
                        "selectionToken": _selection_token(section_name, key_str),
                    }
                )
            elif _canonical_json(base_map[key]) != _canonical_json(incoming_map[key]):
                key_str = str(key)
                changed.append(key_str)
                changed_details.append(
                    {
                        "key": key_str,
                        "beforePreview": _preview_value(base_map[key]),
                        "afterPreview": _preview_value(incoming_map[key]),
                        "selectionToken": _selection_token(section_name, key_str),
                    }
                )
            else:
                unchanged.append(str(key))
        if section_name == "threadState":
            base_files = _thread_state_file_map({"__files": base_map.get("__files")})
            incoming_files = _thread_state_file_map({"__files": incoming_map.get("__files")})
            all_file_keys = sorted(set(base_files.keys()) | set(incoming_files.keys()))
            for key in all_file_keys:
                file_key = f"__files:{key}"
                token = _selection_token("threadState.__files", str(key))
                if key not in base_files:
                    added.append(file_key)
                    added_details.append({"key": file_key, "preview": _preview_value(incoming_files[key]), "selectionToken": token})
                elif key not in incoming_files:
                    removed.append(file_key)
                    removed_details.append({"key": file_key, "preview": _preview_value(base_files[key]), "selectionToken": token})
                elif _canonical_json(base_files[key]) != _canonical_json(incoming_files[key]):
                    changed.append(file_key)
                    changed_details.append(
                        {
                            "key": file_key,
                            "beforePreview": _preview_value(base_files[key]),
                            "afterPreview": _preview_value(incoming_files[key]),
                            "selectionToken": token,
                        }
                    )
        return {
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged": unchanged,
            "addedDetails": added_details,
            "removedDetails": removed_details,
            "changedDetails": changed_details,
            "addedCount": len(added),
            "removedCount": len(removed),
            "changedCount": len(changed),
            "unchangedCount": len(unchanged),
        }

    return {
        "reviews": diff_mapping(base["reviews"], incoming["reviews"], section_name="reviews"),
        "groupBriefs": diff_mapping(base["groupBriefs"], incoming["groupBriefs"], section_name="groupBriefs"),
        "analysisState": diff_mapping(base["analysisState"], incoming["analysisState"], section_name="analysisState"),
        "threadState": diff_mapping(base["threadState"], incoming["threadState"], section_name="threadState"),
    }


def iter_review_state_diff_rows(diff: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for section_name in STATE_DIFF_SECTIONS:
        section = diff.get(section_name, {}) if isinstance(diff.get(section_name), dict) else {}
        for detail_key, change_kind in (
            ("addedDetails", "added"),
            ("removedDetails", "removed"),
            ("changedDetails", "changed"),
        ):
            items = section.get(detail_key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                preview = str(item.get("preview", ""))
                if change_kind == "changed":
                    preview = f"{item.get('beforePreview', '')} -> {item.get('afterPreview', '')}"
                rows.append(
                    {
                        "section": section_name,
                        "changeKind": change_kind,
                        "key": str(item.get("key", "")),
                        "preview": preview,
                        "selectionToken": str(item.get("selectionToken", "")),
                    }
                )
    return rows


def _selection_tokens_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    section_order = {name: index for index, name in enumerate(STATE_DIFF_SECTIONS, start=1)}
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            section_order.get(str(row.get("section", "")), 99),
            str(row.get("selectionToken", "")),
            str(row.get("changeKind", "")),
            str(row.get("key", "")),
        ),
    )
    seen: set[str] = set()
    tokens: list[str] = []
    for row in sorted_rows:
        token = str(row.get("selectionToken", "")).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def iter_review_state_selection_tokens(diff: dict[str, Any]) -> list[str]:
    return _selection_tokens_from_rows(iter_review_state_diff_rows(diff))


def summarize_merge_warnings(warnings: list[str]) -> dict[str, Any]:
    sections = {"reviews": 0, "groupBriefs": 0, "analysisState": 0, "threadState": 0, "other": 0}
    kinds = {
        "statusConflict": 0,
        "chunkCommentConflict": 0,
        "groupBriefConflict": 0,
        "invalidReviewRecord": 0,
        "invalidGroupBriefRecord": 0,
        "other": 0,
    }
    for warning in warnings:
        text = str(warning)
        if "chunk " in text or "review record" in text or "status conflict on chunk" in text:
            sections["reviews"] += 1
        elif "group brief" in text:
            sections["groupBriefs"] += 1
        elif "analysisState" in text:
            sections["analysisState"] += 1
        elif "threadState" in text:
            sections["threadState"] += 1
        else:
            sections["other"] += 1
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
        else:
            kinds["other"] += 1
    return {
        "total": len(warnings),
        "sections": sections,
        "kinds": kinds,
    }


def summarize_merge_result(
    base_state: dict[str, Any],
    merged_state: dict[str, Any],
    warnings: list[str],
    *,
    incoming_states: list[tuple[str, dict[str, Any]]] | None = None,
    applied: int | None = None,
) -> dict[str, Any]:
    return {
        "diff": diff_review_states(base_state, merged_state),
        "warnings": summarize_merge_warnings(warnings),
        "briefChanges": summarize_group_brief_changes(base_state, merged_state),
        "inputs": summarize_incoming_state_inputs(incoming_states or []),
        "applied": int(applied or 0),
    }


def summarize_review_state(state: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_review_state_payload(state)
    reviews = normalized["reviews"]
    group_briefs = normalized["groupBriefs"]
    analysis_state = normalized["analysisState"]
    thread_state = normalized["threadState"]

    review_status_counts = {
        "unreviewed": 0,
        "reviewed": 0,
        "ignored": 0,
        "needsReReview": 0,
        "invalid": 0,
    }
    comment_chunk_count = 0
    line_comment_count = 0
    for record in reviews.values():
        if not isinstance(record, dict):
            review_status_counts["invalid"] += 1
            continue
        status = _normalize_review_status(record.get("status"))
        if status is None:
            review_status_counts["invalid"] += 1
        else:
            review_status_counts[status] += 1
        if _normalize_comment(record.get("comment")):
            comment_chunk_count += 1
        line_comment_count += len(_normalized_line_comments(record))

    brief_status_counts = {"draft": 0, "ready": 0, "acknowledged": 0, "stale": 0, "invalid": 0}
    for record in group_briefs.values():
        if not isinstance(record, dict):
            brief_status_counts["invalid"] += 1
            continue
        status = _normalize_group_brief_status(record.get("status"))
        if status is None:
            brief_status_counts["invalid"] += 1
        else:
            brief_status_counts[status] += 1

    file_thread_state = thread_state.get("__files", {}) if isinstance(thread_state.get("__files"), dict) else {}
    thread_chunk_entry_count = sum(1 for key in thread_state.keys() if key not in {"__files", "selectedLineAnchor"})

    return {
        "reviews": {
            "total": len(reviews),
            "statusCounts": review_status_counts,
            "chunkCommentCount": comment_chunk_count,
            "lineCommentCount": line_comment_count,
        },
        "groupBriefs": {
            "total": len(group_briefs),
            "statusCounts": brief_status_counts,
        },
        "analysisState": {
            "present": bool(analysis_state),
            "currentGroupId": str(analysis_state.get("currentGroupId", "")).strip(),
            "selectedChunkId": str(analysis_state.get("selectedChunkId", "")).strip(),
            "filterText": str(analysis_state.get("filterText", "")).strip(),
            "groupReportMode": bool(analysis_state.get("groupReportMode", False)),
            "chunkDetailViewMode": str(analysis_state.get("chunkDetailViewMode", "")).strip(),
            "showContextLines": bool(analysis_state.get("showContextLines", True)),
        },
        "threadState": {
            "present": bool(thread_state),
            "chunkEntryCount": thread_chunk_entry_count,
            "fileEntryCount": len(file_thread_state),
            "hasSelectedLineAnchor": isinstance(thread_state.get("selectedLineAnchor"), dict),
        },
    }


def build_review_state_diff_report(
    base_state: dict[str, Any],
    other_state: dict[str, Any],
    *,
    source_label: str | None = None,
) -> dict[str, Any]:
    state_diff = diff_review_states(base_state, other_state)
    rows = iter_review_state_diff_rows(state_diff)
    selection_tokens = _selection_tokens_from_rows(rows)
    report: dict[str, Any] = {
        "stateDiff": state_diff,
        "rows": rows,
        "selectionTokens": selection_tokens,
    }
    if source_label is not None:
        report["sourceLabel"] = str(source_label).strip()
    return report


def build_review_state_selection_preview_report(
    base_state: dict[str, Any],
    other_state: dict[str, Any],
    selection_tokens: list[str],
    *,
    source_label: str | None = None,
    base_label: str | None = None,
) -> dict[str, Any]:
    result = preview_review_state_selection(base_state, other_state, selection_tokens)
    report: dict[str, Any] = {
        "selection": result["selection"],
        "rows": result["rows"],
        "summary": result["summary"],
        "resultDiff": result["resultDiff"],
    }
    if source_label is not None:
        report["sourceLabel"] = str(source_label).strip()
    if base_label is not None:
        report["baseLabel"] = str(base_label).strip()
    return report
