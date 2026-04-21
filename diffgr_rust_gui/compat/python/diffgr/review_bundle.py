from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from diffgr.approval import approval_report_to_json, check_all_approvals
from diffgr.generator import sha256_hex
from diffgr.review_state import STATE_KEYS, apply_review_state, extract_review_state, normalize_review_state_payload
from diffgr.viewer_core import load_json, validate_document

BUNDLE_FORMAT = "diffgr-review-bundle"
BUNDLE_VERSION = 1


def _bundle_group_ids(bundle_doc: dict[str, Any]) -> set[str]:
    return {
        str(group.get("id", "")).strip()
        for group in bundle_doc.get("groups", [])
        if isinstance(group, dict) and str(group.get("id", "")).strip()
    }


def _bundle_chunk_ids(bundle_doc: dict[str, Any]) -> set[str]:
    return {
        str(chunk.get("id", "")).strip()
        for chunk in bundle_doc.get("chunks", [])
        if isinstance(chunk, dict) and str(chunk.get("id", "")).strip()
    }


def _bundle_file_keys(bundle_doc: dict[str, Any]) -> set[str]:
    return {
        str(chunk.get("filePath", "")).strip().lower()
        for chunk in bundle_doc.get("chunks", [])
        if isinstance(chunk, dict) and str(chunk.get("filePath", "")).strip()
    }


def _validate_bundle_shape(bundle_doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    reviews = bundle_doc.get("reviews")
    if not isinstance(reviews, dict):
        errors.append("Bundle document `reviews` must be an object.")
    elif reviews:
        errors.append("Bundle document must not contain non-empty `reviews`; mutable review state belongs in review.state.json.")

    for key in STATE_KEYS:
        if key == "reviews":
            continue
        if key in bundle_doc:
            errors.append(f"Bundle document must not contain mutable state key: {key}.")
    return errors


def _validate_state_topology(bundle_doc: dict[str, Any], normalized_state: dict[str, Any]) -> list[str]:
    """Return topology warnings for state keys that reference unknown bundle entities.

    All mismatches are warnings (not errors): a stale state file produced by a rebase
    that removed chunks/groups is not a sign of tampering.  The manifest digest check
    is the authoritative integrity gate.
    """
    warnings: list[str] = []

    group_ids = _bundle_group_ids(bundle_doc)
    chunk_ids = _bundle_chunk_ids(bundle_doc)
    file_keys = _bundle_file_keys(bundle_doc)

    for chunk_id in normalized_state.get("reviews", {}).keys():
        chunk_id_str = str(chunk_id).strip()
        if chunk_id_str and chunk_id_str not in chunk_ids:
            warnings.append(f"State review key not found in bundle chunks: {chunk_id_str}")

    for group_id in normalized_state.get("groupBriefs", {}).keys():
        group_id_str = str(group_id).strip()
        if group_id_str and group_id_str not in group_ids:
            warnings.append(f"State groupBrief key not found in bundle groups: {group_id_str}")

    analysis_state = normalized_state.get("analysisState", {})
    if isinstance(analysis_state, dict):
        current_group_id = str(analysis_state.get("currentGroupId", "")).strip()
        if current_group_id and current_group_id not in group_ids:
            warnings.append(f"analysisState.currentGroupId is not present in bundle groups: {current_group_id}")
        selected_chunk_id = str(analysis_state.get("selectedChunkId", "")).strip()
        if selected_chunk_id and selected_chunk_id not in chunk_ids:
            warnings.append(f"analysisState.selectedChunkId is not present in bundle chunks: {selected_chunk_id}")

    thread_state = normalized_state.get("threadState", {})
    if isinstance(thread_state, dict):
        file_state = thread_state.get("__files")
        if isinstance(file_state, dict):
            for file_key in file_state.keys():
                file_key_str = str(file_key).strip().lower()
                if file_key_str and file_key_str not in file_keys:
                    warnings.append(f"threadState.__files entry is not present in bundle files: {file_key}")
        for key in thread_state.keys():
            key_str = str(key).strip()
            if not key_str or key_str in {"__files", "selectedLineAnchor"}:
                continue
            if key_str not in chunk_ids:
                warnings.append(f"threadState chunk entry is not present in bundle chunks: {key_str}")

    return warnings


def _bundle_doc_without_mutable_state(doc: dict[str, Any]) -> dict[str, Any]:
    bundle = copy.deepcopy(doc)
    bundle["reviews"] = {}
    for key in STATE_KEYS:
        if key == "reviews":
            continue
        bundle.pop(key, None)
    return bundle


def split_document_into_bundle(doc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle_doc = _bundle_doc_without_mutable_state(doc)
    state = extract_review_state(doc)
    return bundle_doc, state


def compose_document_from_bundle(bundle_doc: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    normalized_state = normalize_review_state_payload(state)
    return apply_review_state(bundle_doc, normalized_state)


def build_review_bundle_manifest(bundle_doc: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    normalized_state = normalize_review_state_payload(state)
    source = bundle_doc.get("meta", {}).get("source", {}) if isinstance(bundle_doc.get("meta"), dict) else {}
    source_head = str(source.get("headSha") or source.get("head") or "").strip()
    document_digest = sha256_hex(bundle_doc)
    state_digest = sha256_hex(normalized_state)
    bundle_digest = sha256_hex({"documentDigest": document_digest, "stateDigest": state_digest})
    return {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "sourceHead": source_head,
        "documentDigest": document_digest,
        "stateDigest": state_digest,
        "bundleDigest": bundle_digest,
        "groupCount": len([g for g in bundle_doc.get("groups", []) if isinstance(g, dict)]),
        "chunkCount": len([c for c in bundle_doc.get("chunks", []) if isinstance(c, dict)]),
        "stateKeys": list(STATE_KEYS),
    }


def verify_review_bundle_artifacts(
    bundle_doc: dict[str, Any],
    state: dict[str, Any],
    manifest: dict[str, Any],
    *,
    expected_head: str | None = None,
    require_approvals: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    errors.extend(_validate_bundle_shape(bundle_doc))

    normalized_state = normalize_review_state_payload(state)
    warnings.extend(_validate_state_topology(bundle_doc, normalized_state))

    composed = compose_document_from_bundle(bundle_doc, normalized_state)
    warnings.extend(validate_document(composed))

    if manifest.get("format") != BUNDLE_FORMAT:
        errors.append(f"Unsupported manifest format: {manifest.get('format')!r}")
    if manifest.get("version") != BUNDLE_VERSION:
        errors.append(f"Unsupported manifest version: {manifest.get('version')!r}")

    actual_manifest = build_review_bundle_manifest(bundle_doc, normalized_state)
    for key in ("sourceHead", "documentDigest", "stateDigest", "bundleDigest", "groupCount", "chunkCount"):
        if str(manifest.get(key, "")) != str(actual_manifest.get(key, "")):
            errors.append(f"Manifest mismatch for {key}.")
    if list(manifest.get("stateKeys", [])) != list(actual_manifest.get("stateKeys", [])):
        errors.append("Manifest mismatch for stateKeys.")

    if expected_head is not None:
        expected = str(expected_head).strip()
        actual = str(actual_manifest.get("sourceHead", "")).strip()
        if expected and actual and expected != actual:
            errors.append(f"Expected head {expected} but bundle targets {actual}.")

    approval_json = None
    if require_approvals:
        approval_report = check_all_approvals(composed)
        approval_json = json.loads(approval_report_to_json(approval_report))
        if not approval_report.all_approved:
            errors.append("Not all groups are approved.")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "computedManifest": actual_manifest,
        "approvalReport": approval_json,
    }


def load_bundle_artifacts(
    *,
    bundle_path: Path,
    state_path: Path,
    manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    bundle_doc = load_json(bundle_path)
    state = load_json(state_path)
    manifest = load_json(manifest_path)
    return bundle_doc, state, manifest


