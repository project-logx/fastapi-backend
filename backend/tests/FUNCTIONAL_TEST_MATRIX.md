# Functional Test Matrix

This matrix maps product functionality to automated API-level behavior tests.

## A. System and Source Contract
1. Health contract and source-mode contract are valid.
2. Mock-only mode guarantees no live dependency for functional testing.

Covered by:
- `test_source_mode_contract`
- `test_health_and_capture_config`

## B. Mock Event Ingestion and State Machine
1. Entry mock event creates pending entry.
2. Exit mock event creates pending exit.
3. Duplicate event replay is idempotent.
4. Batch event processing handles mixed scenarios.
5. Position flip closes old path and opens new pending entry.

Covered by:
- `test_mock_entry_creates_pending_entry_and_duplicate_is_deduped`
- `test_batch_events_and_history_limit`
- `test_flip_transition_creates_pending_exit_and_new_pending_entry`

## C. Queue, Trade, and Journey Functional Paths
1. Pending queue grouping and symbol filter.
2. Queue limit boundary behavior.
3. Active trades visibility after entry capture.
4. Journey creation only after complete lifecycle.
5. Incomplete journeys are not replay-eligible.

Covered by:
- `test_queue_filter_and_limit_contract`
- `test_full_lifecycle_with_mid_exit_and_journey_replay`
- `test_journey_endpoint_for_incomplete_trade_returns_409`
- `test_replay_contract_includes_nodes_in_chronological_order`

## D. Node Capture Functional Rules
1. Valid entry/mid/exit submissions with sliders, tags, notes.
2. State-restricted transitions for entry/mid/exit.
3. Exit-only tags blocked outside exit nodes.
4. Slider schema completeness and range checks.
5. JSON form payload integrity validation.

Covered by:
- `test_full_lifecycle_with_mid_exit_and_journey_replay`
- `test_mid_node_not_allowed_while_pending_entry`
- `test_entry_rejects_exit_only_tags`
- `test_slider_validation_missing_dimension`
- `test_node_endpoint_rejects_invalid_json_form_fields`

## E. Custom Tag Functional Rules
1. Create/list/update/archive lifecycle.
2. Case-insensitive uniqueness.
3. Reserved name/pattern and malformed name rejection.
4. Archived visibility via include_archived behavior.
5. Reactivation behavior when creating archived names.

Covered by:
- `test_custom_tag_validation_and_archive_flow`
- `test_include_archived_custom_tags_query`

## F. Attachments Functional Rules
1. Allowed file types accepted.
2. Unsupported mime rejected.
3. Maximum files per node enforced.
4. Maximum size per file enforced.
5. Duplicate binary payload deduped per node.
6. Listing and retrieval functional paths.
7. Deletion blocked for completed journeys (immutability).

Covered by:
- `test_attachment_type_validation`
- `test_attachment_limit_enforced_at_10_files`
- `test_attachment_size_limit_enforced`
- `test_duplicate_attachment_payload_is_deduplicated_per_node`
- `test_attachment_endpoints_and_immutability`
- `test_delete_missing_attachment_returns_404`

## G. Reset and Deterministic Environment Controls
1. Reset endpoint cleans runtime state.
2. Reset with keep_tags preserves tag taxonomy when requested.

Covered by:
- `test_reset_keep_tags_true_preserves_tag_rows`
- Existing reset behavior in test fixtures (`conftest.py`).

## Execution
Run all backend functional tests:

```powershell
c:/Users/Lenovo/OneDrive/Desktop/logx/.venv/Scripts/python.exe -m pytest backend
```
