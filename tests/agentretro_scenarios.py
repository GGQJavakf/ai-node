"""Executable OpenSpec scenario-to-pytest traceability for AgentRetro."""

SCENARIO_TESTS: dict[str, tuple[str, ...]] = {
    # Codex session retrospective
    "CR-01": (
        "tests/test_agentretro_capture.py::test_cli_capture_last_then_named_session_uses_only_injected_paths",
    ),
    "CR-02": (
        "tests/test_agentretro_capture.py::test_cli_capture_last_then_named_session_uses_only_injected_paths",
    ),
    "CR-03": ("tests/test_agentretro_capture.py::test_active_session_is_rejected",),
    "CR-04": (
        "tests/test_agentretro_capture.py::test_completed_capture_starts_no_hook_watcher_daemon_or_background_work",
    ),
    "CR-05": (
        "tests/test_agentretro_capture.py::test_effective_codex_home_prefers_explicit_environment",
    ),
    "CR-06": (
        "tests/test_agentretro_capture.py::test_unavailable_codex_source_reports_diagnostic_and_creates_no_partial_state",
    ),
    "CR-07": (
        "tests/test_agentretro_capture.py::test_capture_is_redacted_transactional_idempotent_and_integrity_checked",
    ),
    "CR-08": (
        "tests/test_agentretro_capture.py::test_capture_is_redacted_transactional_idempotent_and_integrity_checked",
    ),
    "CR-09": (
        "tests/test_agentretro_capture.py::test_unknown_optional_event_is_diagnosed_and_never_normalized",
    ),
    "CR-10": (
        "tests/test_agentretro_capture.py::test_parser_failure_creates_no_partial_capture",
    ),
    "CR-11": (
        "tests/test_agentretro_capture.py::test_project_resolver_uses_root_then_unique_remote",
    ),
    "CR-12": (
        "tests/test_agentretro_capture.py::test_project_resolver_reports_ambiguous_when_remote_matches_distinct_projects",
        "tests/test_agentretro_capture.py::test_project_resolver_uses_root_then_unique_remote",
        "tests/test_agentretro_capture.py::test_project_mapping_rejects_vault_escape_and_incompatible_collision",
        "tests/test_agentretro_review.py::test_each_deterministic_gate_blocks[candidate2-review2-evidence2-unknown_project]",
    ),
    "CR-13": (
        "tests/test_agentretro_persistence.py::test_capture_round_trips_complete_evidence_locators_without_derivation",
        "tests/test_agentretro_e2e.py::test_tmp_only_capture_review_accept_sync_and_brief_product_path",
    ),
    "CR-14": (
        "tests/test_agentretro_security.py::test_unique_secret_is_absent_from_every_tmp_artifact_while_proofs_remain",
    ),
    "CR-15": (
        "tests/test_agentretro_capture.py::test_captured_agent_instruction_is_untrusted_evidence_and_is_never_executed",
    ),
    "CR-16": (
        "tests/test_agentretro_capture.py::test_project_mapping_lifecycle_is_sqlite_backed_and_sanitized",
    ),
    "CR-17": (
        "tests/test_agentretro_capture.py::test_project_mapping_rejects_vault_escape_and_incompatible_collision",
    ),
    "CR-18": (
        "tests/test_agentretro_capture.py::test_project_mapping_lifecycle_is_sqlite_backed_and_sanitized",
    ),
    "CR-19": (
        "tests/test_agentretro_capture.py::test_reclassify_reviews_stored_redacted_evidence_before_repository_update",
    ),
    "CR-20": (
        "tests/test_agentretro_capture.py::test_candidate_budget_selects_global_newest_before_stat_and_parse",
        "tests/test_agentretro_capture.py::test_completed_session_is_normalized",
    ),
    "CR-21": (
        "tests/test_agentretro_capture.py::test_oversized_session_is_rejected_before_parse",
    ),
    "CR-22": (
        "tests/test_agentretro_capture.py::test_discovery_timeout_has_an_explicit_diagnostic",
    ),
    # Retrospective knowledge review
    "KR-01": (
        "tests/test_agentretro_review.py::test_real_codex_capture_vocabulary_can_auto_accept_grounded_knowledge[RULE-events0-Always run the focused test first.]",
    ),
    "KR-02": (
        "tests/test_agentretro_review.py::test_real_assistant_evidence_is_not_rule_authority",
    ),
    "KR-03": (
        "tests/test_agentretro_review.py::test_real_codex_capture_vocabulary_can_auto_accept_grounded_knowledge[LESSON-events1-Keep failure, correction, and verification evidence separate.]",
    ),
    "KR-04": (
        "tests/test_agentretro_review.py::test_real_lesson_markers_must_be_explicit_and_on_distinct_evidence",
    ),
    "KR-05": (
        "tests/test_agentretro_review.py::test_auto_accepted_task_state_defaults_to_fourteen_day_validity",
    ),
    "KR-06": (
        "tests/test_agentretro_review.py::test_reviewed_candidate_is_strict_and_requires_complete_contract",
        "tests/test_agentretro_review.py::test_extraction_and_review_use_independent_requests_and_forward_timeout",
    ),
    "KR-07": (
        "tests/test_agentretro_review.py::test_review_failure_is_sanitized_immutable_and_keeps_candidate_pending[model]",
    ),
    "KR-08": (
        "tests/test_agentretro_review.py::test_auto_acceptance_audit_records_threshold_gates_actor_and_evidence",
    ),
    "KR-09": (
        "tests/test_agentretro_review.py::test_non_acceptable_review_result_is_saved_but_candidate_stays_pending[below-threshold]",
    ),
    "KR-10": (
        "tests/test_agentretro_review.py::test_gate_blockers_are_returned_in_stable_policy_order",
    ),
    "KR-11": (
        "tests/test_agentretro_knowledge.py::test_manual_accept_is_pending_only_and_preserves_evidence_with_user_audit",
    ),
    "KR-12": (
        "tests/test_agentretro_knowledge.py::test_manual_edit_can_change_text_type_scope_and_validity_before_acceptance",
    ),
    "KR-13": (
        "tests/test_agentretro_knowledge.py::test_manual_reject_stays_out_of_active_knowledge_and_retains_audit",
    ),
    "KR-14": (
        "tests/test_agentretro_review.py::test_valid_model_conflict_is_redacted_deterministic_and_idempotent",
    ),
    "KR-15": (
        "tests/test_agentretro_knowledge.py::test_conflict_keeps_old_active_until_user_resolution_creates_version",
    ),
    "KR-16": (
        "tests/test_agentretro_knowledge.py::test_global_promotion_and_archive_create_versions_and_preserve_history",
    ),
    "KR-17": (
        "tests/test_agentretro_knowledge.py::test_expired_task_state_becomes_stale_without_deletion",
    ),
    "KR-18": (
        "tests/test_agentretro_knowledge.py::test_global_promotion_and_archive_create_versions_and_preserve_history",
    ),
    "KR-19": (
        "tests/test_agentretro_purge.py::test_plan_is_read_only_complete_redacted_and_deterministic",
    ),
    "KR-20": (
        "tests/test_agentretro_purge.py::test_apply_journals_and_scrubs_sqlite_in_one_stage_without_claiming_purged",
        "tests/test_agentretro_purge.py::test_success_replaces_content_derived_journal_with_opaque_tombstone",
    ),
    "KR-21": (
        "tests/test_agentretro_purge.py::test_atomic_file_failure_marks_incomplete_without_success",
    ),
    "KR-22": (
        "tests/test_agentretro_knowledge.py::test_conflict_keeps_old_active_until_user_resolution_creates_version",
        "tests/test_agentretro_knowledge.py::test_global_promotion_and_archive_create_versions_and_preserve_history",
    ),
    "KR-23": (
        "tests/test_agentretro_review.py::test_completed_review_retry_reuses_result_without_new_request_or_knowledge",
    ),
    "KR-24": (
        "tests/test_agentretro_review.py::test_retry_session_only_calls_model_for_pending_model_dependent_candidates",
    ),
    # Obsidian knowledge sync
    "OS-01": (
        "tests/test_agentretro_obsidian.py::test_three_types_render_to_deterministic_aggregate_files",
    ),
    "OS-02": (
        "tests/test_agentretro_obsidian.py::test_three_types_render_to_deterministic_aggregate_files",
    ),
    "OS-03": (
        "tests/test_agentretro_obsidian.py::test_three_types_render_to_deterministic_aggregate_files",
    ),
    "OS-04": (
        "tests/test_agentretro_obsidian.py::test_cli_edit_and_archive_each_trigger_one_post_commit_projection",
    ),
    "OS-05": (
        "tests/test_agentretro_obsidian.py::test_same_batch_updates_summary_and_index_only_inside_valid_markers",
    ),
    "OS-06": (
        "tests/test_agentretro_obsidian.py::test_managed_block_rejects_malformed_boundaries[no markers]",
        r"tests/test_agentretro_obsidian.py::test_managed_block_rejects_malformed_boundaries[<!-- agentretro:summary:start project=NPKI -->\n]",
    ),
    "OS-07": (
        "tests/test_agentretro_obsidian.py::test_plan_rejects_project_traversal",
        "tests/test_agentretro_obsidian.py::test_symlink_escape_is_rejected_without_write",
    ),
    "OS-08": (
        "tests/test_agentretro_merge.py::test_successful_sync_persists_verifiable_snapshots_for_every_managed_target",
        "tests/test_agentretro_obsidian.py::test_same_batch_updates_summary_and_index_only_inside_valid_markers",
    ),
    "OS-09": (
        "tests/test_agentretro_obsidian.py::test_later_replace_failure_restores_every_target_exactly",
    ),
    "OS-10": (
        "tests/test_agentretro_obsidian.py::test_restoration_failure_blocks_future_sync",
    ),
    "OS-11": (
        "tests/test_agentretro_obsidian.py::test_cli_accept_keeps_knowledge_when_vault_unavailable_then_sync_retry",
    ),
    "OS-12": (
        "tests/test_agentretro_merge.py::test_external_edit_blocks_automatic_sync_and_preserves_both_versions",
    ),
    "OS-13": (
        "tests/test_agentretro_merge.py::test_adopt_vault_creates_pending_edit_candidate_with_provenance",
    ),
    "OS-14": (
        "tests/test_agentretro_merge.py::test_keep_database_only_creates_replacement_preview_until_apply",
    ),
    "OS-15": (
        "tests/test_agentretro_merge.py::test_create_plan_is_immutable_persistent_complete_and_does_not_write_vault",
    ),
    "OS-16": ("tests/test_agentretro_merge.py::test_repeated_apply_is_idempotent",),
    "OS-17": (
        "tests/test_agentretro_merge.py::test_stale_merge_plan_cannot_apply_and_writes_nothing",
    ),
    "OS-18": (
        "tests/test_agentretro_merge.py::test_general_apply_does_not_authorize_destructive_operations",
        "tests/test_agentretro_merge.py::test_exact_confirmations_apply_delete_rename_and_acknowledged_conflict",
    ),
    "OS-19": (
        "tests/test_agentretro_obsidian.py::test_same_batch_updates_summary_and_index_only_inside_valid_markers",
    ),
    "OS-20": (
        "tests/test_agentretro_purge.py::test_plan_is_read_only_complete_redacted_and_deterministic",
    ),
    "OS-21": (
        "tests/test_agentretro_obsidian.py::test_cli_accept_commits_then_projects_once_in_same_command",
    ),
    "OS-22": (
        "tests/test_agentretro_obsidian.py::test_cli_accept_keeps_knowledge_when_vault_unavailable_then_sync_retry",
    ),
    "OS-23": (
        "tests/test_agentretro_obsidian.py::test_after_commit_is_idempotent_and_log_has_one_event",
    ),
    "OS-24": (
        "tests/test_agentretro_obsidian.py::test_public_apply_rejects_noncanonical_plan_before_any_filesystem_write[extra_prose]",
    ),
    "OS-25": (
        "tests/test_agentretro_obsidian_init.py::test_os_25_preview_is_deterministic_complete_and_zero_write",
    ),
    "OS-26": (
        "tests/test_agentretro_obsidian_init.py::test_os_26_matching_apply_preserves_prose_and_missing_page_stays_missing",
    ),
    "OS-27": (
        "tests/test_agentretro_obsidian_init.py::test_os_27_changed_target_rejects_stale_plan_before_backup_or_write",
    ),
    "OS-28": (
        "tests/test_agentretro_obsidian_init.py::test_os_28_directory_or_symlink_target_is_rejected_without_write",
        "tests/test_agentretro_obsidian_init.py::test_os_28_unsafe_marker_or_encoding_rejects_complete_plan[invalid-utf8-\\xff]",
    ),
    "OS-29": (
        "tests/test_agentretro_obsidian_init.py::test_os_29_multi_target_failure_restores_or_records_rollback_required[False]",
        "tests/test_agentretro_obsidian_init.py::test_os_29_multi_target_failure_restores_or_records_rollback_required[True]",
        "tests/test_agentretro_obsidian_init.py::test_os_29_retry_after_verified_rollback_reuses_retained_backup",
    ),
    # Retrospective briefing and Codex integration
    "BR-01": (
        "tests/test_agentretro_subprocess.py::test_retro_subprocess_smoke_has_defined_exits_and_strict_console_output[utf-8]",
        "tests/test_agentretro_subprocess.py::test_retro_help_does_not_import_todo_or_workitem_application_domain",
    ),
    "BR-02": (
        "tests/test_agentretro_foundation.py::test_legacy_and_retro_entry_points_are_independently_callable",
        "tests/test_agentretro_foundation.py::test_agentretro_initialization_failure_does_not_block_ai_todo_or_touch_its_data",
    ),
    "BR-03": (
        "tests/test_agentretro_foundation.py::test_agentretro_initialization_failure_does_not_block_ai_todo_or_touch_its_data",
    ),
    "BR-04": (
        "tests/test_agentretro_foundation.py::test_legacy_model_client_receives_only_a_fresh_allowlisted_dictionary",
        "tests/test_agentretro_security.py::test_unique_secret_is_absent_from_every_tmp_artifact_while_proofs_remain",
    ),
    "BR-05": (
        "tests/test_agentretro_cli.py::test_model_composition_fails_stably_before_client_build_when_model_is_missing",
        "tests/test_agentretro_capture.py::test_cli_capture_last_then_named_session_uses_only_injected_paths",
        "tests/test_agentretro_task7_cli.py::test_cli_brief_uses_sqlite_service_and_emits_stable_path_free_json",
        "tests/test_agentretro_doctor.py::test_doctor_surfaces_rollback_purge_override_and_missing_model_without_paths",
        "tests/test_agentretro_obsidian.py::test_cli_accept_keeps_knowledge_when_vault_unavailable_then_sync_retry",
        "tests/test_agentretro_review.py::test_review_failure_is_sanitized_immutable_and_keeps_candidate_pending[model]",
    ),
    "BR-06": (
        "tests/test_agentretro_briefing.py::test_brief_selects_only_active_accepted_knowledge_in_fixed_category_order",
        "tests/test_agentretro_briefing.py::test_brief_reports_evidence_conflict_sync_rollback_and_purge_health",
    ),
    "BR-07": (
        "tests/test_agentretro_briefing.py::test_brief_selects_only_active_accepted_knowledge_in_fixed_category_order",
        "tests/test_agentretro_briefing.py::test_brief_reports_evidence_conflict_sync_rollback_and_purge_health",
    ),
    "BR-08": (
        "tests/test_agentretro_briefing.py::test_brief_reports_evidence_conflict_sync_rollback_and_purge_health",
    ),
    "BR-09": (
        "tests/test_agentretro_briefing.py::test_later_items_are_included_or_omitted_atomically_by_utf8_byte_budget",
    ),
    "BR-10": (
        "tests/test_agentretro_briefing.py::test_terminal_markdown_and_json_are_stable_views_of_the_same_result",
    ),
    "BR-11": (
        "tests/test_agentretro_subprocess.py::test_retro_subprocess_smoke_has_defined_exits_and_strict_console_output[gbk]",
        "tests/test_agentretro_subprocess.py::test_retro_subprocess_smoke_has_defined_exits_and_strict_console_output[utf-8]",
    ),
    "BR-12": (
        "tests/test_agentretro_codex_integration.py::test_preview_existing_and_missing_is_complete_and_absolutely_non_writing",
    ),
    "BR-13": (
        "tests/test_agentretro_codex_integration.py::test_apply_and_remove_preserve_every_outside_byte_and_keep_backup",
    ),
    "BR-14": (
        "tests/test_agentretro_codex_integration.py::test_preview_id_is_in_memory_current_and_hash_bound",
    ),
    "BR-15": (
        "tests/test_agentretro_codex_integration.py::test_apply_and_remove_preserve_every_outside_byte_and_keep_backup",
        "tests/test_agentretro_codex_integration.py::test_discovery_reads_only_canonical_target_and_requires_one_exact_block",
    ),
    "BR-16": (
        r"tests/test_agentretro_codex_integration.py::test_manual_duplicate_nested_or_malformed_markers_fail_closed[<!-- agentretro:codex:start version=1 -->\nchanged manually\n<!-- agentretro:codex:end -->\n]",
    ),
    "BR-17": (
        "tests/test_agentretro_codex_integration.py::test_discovery_reads_only_canonical_target_and_requires_one_exact_block",
    ),
    "BR-18": (
        "tests/test_agentretro_briefing.py::test_brief_never_calls_model_vector_vault_or_native_memory",
        "tests/test_agentretro_codex_integration.py::test_discovery_reads_only_canonical_target_and_requires_one_exact_block",
    ),
    "BR-19": (
        "tests/test_agentretro_doctor.py::test_doctor_returns_exact_order_redacted_model_state_and_one_recovery_per_check",
    ),
    "BR-20": (
        "tests/test_agentretro_doctor.py::test_doctor_surfaces_rollback_purge_override_and_missing_model_without_paths",
    ),
    "BR-21": (
        "tests/test_agentretro_briefing.py::test_same_snapshot_and_clock_produce_identical_result",
        "tests/test_agentretro_briefing.py::test_brief_never_calls_model_vector_vault_or_native_memory",
    ),
    "BR-22": (
        "tests/test_agentretro_briefing.py::test_brief_uses_nfkc_casefold_latin_and_cjk_fixed_scoring_and_id_tie_break",
    ),
    "BR-23": (
        "tests/test_agentretro_briefing.py::test_mandatory_rules_over_budget_fail_without_partial_result",
    ),
    "BR-24": (
        "tests/test_agentretro_briefing.py::test_deadline_failure_returns_no_partial_success",
    ),
    "BR-25": (
        "tests/test_agentretro_codex_integration.py::test_missing_file_is_created_only_by_matching_apply_and_remove_restores_absence",
    ),
    "BR-26": (
        "tests/test_agentretro_codex_integration.py::test_override_blocks_apply_and_remove_without_touching_either_file",
        "tests/test_agentretro_doctor.py::test_doctor_surfaces_rollback_purge_override_and_missing_model_without_paths",
        "tests/test_agentretro_task7_cli.py::test_cli_brief_deadline_and_codex_override_have_typed_errors",
    ),
    "BR-27": (
        "tests/test_agentretro_codex_integration.py::test_apply_and_remove_preserve_every_outside_byte_and_keep_backup",
        "tests/test_agentretro_codex_integration.py::test_discovery_reads_only_canonical_target_and_requires_one_exact_block",
    ),
    "BR-28": (
        "tests/test_agentretro_review.py::test_review_failure_is_sanitized_immutable_and_keeps_candidate_pending[timeout]",
        "tests/test_agentretro_foundation.py::test_effective_model_timeout_uses_documented_precedence[None-legacy3-120]",
    ),
}


HARDENING_SCENARIO_TESTS: dict[str, tuple[str, ...]] = {
    "WR-01": (
        "tests/test_agentretro_recent_session_hardening.py::test_non_git_workspace_mapping_routes_contained_session",
    ),
    "WR-02": (
        "tests/test_agentretro_recent_session_hardening.py::test_workspace_mapping_rejects_missing_file_and_symlink_roots",
    ),
    "WR-03": (
        "tests/test_agentretro_recent_session_hardening.py::test_non_git_workspace_mapping_routes_contained_session",
    ),
    "WR-04": (
        "tests/test_agentretro_recent_session_hardening.py::test_workspace_routing_prefers_longest_root_and_stops_on_git_disagreement",
    ),
    "WR-05": (
        "tests/test_agentretro_recent_session_hardening.py::test_workspace_routing_prefers_longest_root_and_stops_on_git_disagreement",
    ),
    "WR-06": (
        "tests/test_agentretro_recent_session_hardening.py::test_non_git_workspace_mapping_routes_contained_session",
    ),
    "SF-01": (
        "tests/test_agentretro_recent_session_hardening.py::test_valid_nested_session_metadata_chain_uses_leaf_identity",
    ),
    "SF-02": (
        "tests/test_agentretro_capture.py::test_completed_session_is_normalized",
    ),
    "SF-03": (
        "tests/test_agentretro_recent_session_hardening.py::test_invalid_repeated_session_metadata_remains_fail_closed[unrelated]",
    ),
    "SF-04": (
        "tests/test_agentretro_recent_session_hardening.py::test_invalid_repeated_session_metadata_remains_fail_closed[post_event]",
    ),
    "SF-05": (
        "tests/test_agentretro_recent_session_hardening.py::test_invalid_repeated_session_metadata_remains_fail_closed[family_conflict]",
    ),
    "SF-06": (
        "tests/test_agentretro_recent_session_hardening.py::test_valid_nested_session_metadata_chain_uses_leaf_identity",
    ),
    "IQ-01": (
        "tests/test_agentretro_recent_session_hardening.py::test_optional_event_warnings_are_aggregated_by_type",
    ),
    "IQ-02": (
        "tests/test_agentretro_recent_session_hardening.py::test_valid_nested_session_metadata_chain_uses_leaf_identity",
    ),
    "IQ-03": (
        "tests/test_agentretro_recent_session_hardening.py::test_duplicate_evidence_is_canonical_with_all_source_locators",
    ),
    "IQ-04": (
        "tests/test_agentretro_recent_session_hardening.py::test_equal_content_with_different_kinds_remains_distinct_evidence",
    ),
    "IQ-05": (
        "tests/test_agentretro_recent_session_hardening.py::test_duplicate_evidence_is_canonical_with_all_source_locators",
    ),
    "IQ-06": (
        "tests/test_agentretro_recent_session_hardening.py::test_duplicate_evidence_is_canonical_with_all_source_locators",
    ),
    "RR-01": (
        "tests/test_agentretro_recent_session_hardening.py::test_structured_review_failure_gets_one_fresh_observable_retry",
    ),
    "RR-02": (
        "tests/test_agentretro_review.py::test_review_failure_is_sanitized_immutable_and_keeps_candidate_pending[strict-parse]",
    ),
    "RR-03": (
        "tests/test_agentretro_recent_session_hardening.py::test_non_retryable_review_failure_is_not_automatically_repeated",
    ),
    "RR-04": (
        "tests/test_agentretro_recent_session_hardening.py::test_structured_review_failure_gets_one_fresh_observable_retry",
    ),
    "RR-05": (
        "tests/test_agentretro_recent_session_hardening.py::test_schema_v3_migration_is_backup_first_and_backfills_existing_rows",
    ),
    "RR-06": (
        "tests/test_agentretro_review.py::test_completed_review_retry_reuses_result_without_new_request_or_knowledge",
    ),
}


def scenario_verification_rows() -> tuple[str, ...]:
    """Render the human-readable verification evidence from the canonical registry."""
    return tuple(
        f"{scenario_id}: {', '.join(node_ids)}"
        for scenario_id, node_ids in sorted(SCENARIO_TESTS.items())
    )
