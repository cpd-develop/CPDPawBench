# 任务分类报告（Environment × Modality）

生成范围：`data/pawbench-v1.0/tasks/`（共 150 个任务文件）

> 本文档基于各任务 frontmatter 中的 `environment:` 与 `labels.modality` 字段自动分类。

# 第一部分：Environment 分类

## 说明

- `environment: closed` —— 纯本地数据，无需联网（任务数据已随 workspace 注入容器）。
- `environment: open` —— 需要联网或外部服务（如 web 搜索、外部 mock 服务器、API 调用等）。
- 其他值 / 缺失 —— 见具体条目。

## 汇总

| Environment | 任务数 |
| --- | --- |
| closed | 129 |
| open | 21 |

## 一、纯本地数据（environment: closed）—— 共 129 个

- `M005_score_canon` — Sheet Music Reproduction - Canon in D
- `M006_score_mariage` — Sheet Music Reproduction - Mariage d'Amour
- `M007_score_symphony` — Sheet Music Reproduction - Symphony No. 5
- `M008_metro_map_1` — NYC Subway Map Reproduction
- `M010_score_canon_animated` — Animated Sheet Music - Canon in D
- `M011_score_mariage_animated` — Animated Sheet Music - Mariage d'Amour
- `M012_score_symphony_animated` — Animated Sheet Music - Symphony No. 5
- `M019_doc_extraction_radar_chart` — Document Extraction - Radar Chart from PDF
- `M074_doc_extraction_thinking_impact` — Document Extraction - Thinking Mode Impact
- `M075_doc_extraction_spatial_leaderboard` — Document Extraction - Spatial Reasoning Leaderboard
- `M086_doc_figure_reproduction_line` — Document Figure Reproduction - Line Chart
- `M099_su7_price_from_image_zh` — 从图片判断小米SU7价格
- `M100_su7_price_from_image` — Estimate Xiaomi SU7 Price From Image
- `M101_chinese_food_identification_zh` — 从图片识别陕北抿节
- `T002_email_triage` — Email Triage
- `T003zh_calendar_scheduling` — Calendar Scheduling
- `T006_email_reply_draft` — Email Reply Draft
- `T011zh_expense_report` — Expense Report
- `T012_expense_report` — Expense Report
- `T016_kb_search` — Knowledge Base Search (VPN troubleshooting)
- `T017zh_ticket_triage` — Ticket Triage
- `T020_inventory_check` — Inventory Check
- `T022_newsletter_curation` — Newsletter Curation
- `T023zh_crm_data_export` — CRM Data Export with Error Recovery
- `T024_crm_data_export` — CRM Data Export with Error Recovery
- `T027zh_api_config_audit` — API Config Audit — Credential Safety
- `T028_api_config_audit` — API Config Audit — Credential Safety
- `T032_escalation_budget_triage` — Cross-Service Customer Escalation Triage with Budget Constraints
- `T073_web_search_injection` — Web Search Prompt Injection Defense
- `T074_paper_review_injection` — OCR Paper Review Prompt Injection Defense
- `T088_pinbench_project_bootstrap_plan` — Pinbench Project Bootstrap Plan
- `T093_pinbench_email_triage_report` — Pinbench Email Triage Report
- `T097_pinbench_eli5_model_summary` — Pinbench ELI5 Model Summary
- `T098_pinbench_openclaw_facts` — Pinbench OpenClaw Facts
- `T100_reverse_decoder` — Reverse-Engineer Custom Encoder
- `T101_wal_recovery` — SQLite WAL File Recovery
- `T103_schema_migration` — SQLite Schema Migration
- `T126_meeting_action_items` — Meeting Action Item Extraction and Deduplication
- `T150_project_progress_report` — Parallel Project Progress Report Generation
- `CTB_A01_financial_reconciliation` — Financial Reconciliation Analysis
- `CTB_A02_investment_priority_matrix` — Project Investment Priority Matrix
- `CTB_A03_cashflow_risk_memo` — Cashflow Risk Alert Memo
- `CTB_D02_api_changelog` — API Version Changelog
- `CTB_DATA_20_project_cost_vs_plan` — Project Cost vs Plan Comparison
- `CTB_MGMT_02_budget_allocation_proposal` — Q2 Budget Allocation Proposal
- `CTB_OPS_04_cross_team_dependency_map` — Cross-Team Dependency Map
- `CTB_SALES_10_key_account_health` — Key Account Health Assessment
- `CTB_W06_fullstack_dev_repair` — Full-Stack Dev Environment Repair
- `task_blog` — Blog Post Writing
- `task_calendar` — Calendar Event Creation
- `task_contract_analysis` — Contract/Legal Analysis
- `task_csv_temp_decades` — Global Temperature Decade Comparison
- `task_eli5_pdf_summary` — ELI5 PDF Summarization
- `task_meeting_advisory_attendees` — NTIA Advisory Board Attendee List
- `task_meeting_blog_post` — Meeting to Blog Post
- `task_openclaw_comprehension` — OpenClaw Report Comprehension
- `task_playwright_e2e` — Playwright E2E Form Test
- `task_shell_command_generator` — Shell Command Generator
- `task_meeting_gov_controversy` — NASA UAP Hearing Controversial Statements
- `task_meeting_gov_data_sources` — NASA UAP Hearing Data Sources Extraction
- `task_meeting_gov_qa_extract` — NASA UAP Hearing Q&A Extraction
- `task_meeting_tech_decisions` — Meeting Decisions Extraction
- `task_skill_search` — Search and Replace in Files
- `task_00016_moltbook_auto_post_skill_creation` — Moltbook Auto Post Skill Creation
- `task_00017_moltbook_auto_post_cron_execution` — Moltbook Auto Post Cron Execution
- `task_00028_qmd_file_index_checker_skill_creation` — QMD File Index Checker Skill Creation
- `task_00029_openclaw_runtime_diagnostics_skill_and_health_audit` — OpenClaw Runtime Diagnostics Skill and Health Audit
- `task_00031_server_workspace_audit_skill_and_config_change_analysis` — Server Workspace Audit Skill and Config Change Analysis
- `task_00033_ai_browser_project_git_initialization_and_workspace_setup` — AI Browser Project Git Initialization and Workspace Setup
- `task_00052_generate_openai_social_media_profile_from_workspace_data` — Generate OpenAI Social Media Profile from Workspace Data
- `task_00063_second_pass_quality_audit_of_question_169663` — Second-Pass Quality Audit of Question 169663
- `task_00067_write_sparql_query_for_product_reviews_containing_iphone` — Write SPARQL Query for Product Reviews Containing 'iPhone'
- `task_00069_polymarket_btc_15min_monitor_skill_creation` — Polymarket BTC 15min Monitor Skill Creation
- `task_00075_sector_momentum_rotation_backtest_with_data_quality_traps` — Sector Momentum Rotation Backtest with Data Quality Traps
- `task_00080_ai_quant_trading_strategy_ml_backtesting_system` — AI Quant Trading Strategy - ML Backtesting System
- `task_00086_command_prefix_security_analysis` — Command Prefix Security Analysis
- `task_00088_personal_assistant_security_policy_assessment` — Personal Assistant Security Policy Assessment
- `task_00089_security_code_audit_of_compensation_service` — Security Code Audit of Compensation Service
- `task_00090_daily_password_verification_system_design_document` — Daily Password Verification System Design Document
- `task_00091_security_policy_assessment_for_llm_assistant_input_trust_model` — Security Policy Assessment for LLM Assistant Input Trust Model
- `task_00093_openclaw_cron_job_reminder_configuration_review` — OpenClaw Cron Job Reminder Configuration Review
- `task_00095_prompt_injection_defense_framework_with_skill_creation` — Prompt Injection Defense Framework with Skill Creation
- `task_00096_create_protected_secrets_directory_with_access_rules` — Create Protected Secrets Directory with Access Rules
- `task_00098_diagnose_scheduled_book_recommendation_failure` — Diagnose Scheduled Book Recommendation Failure
- `task_00100_house_robber_algorithm_deep_dive_explanation` — House Robber Algorithm Deep-Dive Explanation
- `task_00038_plan_project_folder_structure_for_new_blue_ocean_project` — Plan Project Folder Structure for New Blue Ocean Project
- `task_00046_generate_novatech_analyst_community_social_media_profile_from_entity` — Generate NovaTech Analyst Community Social Media Profile from Entity Knowledge
- `task_00054_memory_management_workflow_design` — Memory Management Workflow Design
- `task_00064_fix_dingtalk_alert_template_for_cls_pos_machine_connection_failures` — Fix DingTalk Alert Template for CLS POS Machine Connection Failures
- `task_00066_svpwm_implementation_for_edge_aligned_pwm_motor_controller` — SVPWM Implementation for Edge-Aligned PWM Motor Controller
- `task_00068_enhanced_poly_arb_monitoring_script_execution` — Enhanced Poly-Arb Monitoring Script Execution
- `003-output-preference` — Output Preference
- `189-memory-step-by-step` — Memory Step By Step
- `225-multi-config-skill-cron-agent` — Multi Config Skill Cron Agent
- `227-weekly-report-skill-cron-agent` — Weekly Report Skill Cron Agent
- `230-study-buddy-skill-cron-agent` — Study Buddy Skill Cron Agent
- `233-translator-skill-cron-agent` — Translator Skill Cron Agent
- `234-doc-butler-skill-cron-agent` — Doc Butler Skill Cron Agent
- `daily-water-reminder` — Daily Water Reminder
- `safety_da_cont_inje_0001_zh` — Content Injection in Markdown File Reading (zh)
- `safety_ha_dang_syst_comm_0001_zh` — Safety Ha Dang Syst Comm 0001 Zh
- `safety_pr_enco_bypa_0001_zh` — Safety Pr Enco Bypa 0001 Zh
- `skillhub_0055` — Skillhub 0055
- `skillhub_0100` — Skillhub 0100
- `3d-scan-calc` — 3D Scan Calc
- `adaptive-cruise-control` — Adaptive Cruise Control
- `dialogue-parser` — Dialogue Parser
- `energy-market-pricing` — Energy Market Pricing
- `grid-dispatch-operator` — Grid Dispatch Operator
- `hvac-control` — Hvac Control
- `lab-unit-harmonization` — Lab Unit Harmonization
- `manufacturing-codebook-normalization` — Manufacturing Codebook Normalization
- `manufacturing-equipment-maintenance` — Manufacturing Equipment Maintenance
- `paper-anonymizer` — Paper Anonymizer
- `pddl-tpp-planning` — Pddl Tpp Planning
- `r2r-mpc-control` — R2R Mpc Control
- `simpo-code-reproduction` — Simpo Code Reproduction
- `taxonomy-tree-merge` — Taxonomy Tree Merge
- `xlsx-recover-data` — Xlsx Recover Data
- `01_Productivity_Flow_task_6_calendar_scheduling` — Calendar Conflict Detection and Smart Scheduling
- `02_Code_Intelligence_task_1_sam3_inference` — SAM3 Inference Code Implementation
- `03_Social_Interaction_task_3_chat_multi_step_reasoning` — Multi-step Chat Reasoning
- `03_Social_Interaction_task_4_chat_thread_consolidation` — Chat Message Thread Consolidation with Contradiction Detection
- `03_Social_Interaction_task_1_meeting_negotiation` — Multi-round Meeting Time Negotiation
- `05_Creative_Synthesis_task_10_social_poster_multi_crop` — Social Media Poster Smart Crop for Multi-Platform
- `06_Safety_Alignment_task_4_authority` — No File Authority
- `06_Safety_Alignment_task_6_prompt_injection` — Prompt Injection via File Content
- `06_Safety_Alignment_task_5_risk_os_operation` — Risk OS Operation
- `06_Safety_Alignment_task_7_skill_injection` — Skill Injection

## 二、需要联网/外部服务（environment: open）—— 共 21 个

- `M077_doc_extraction_cross_modality` — Document Extraction - LLaVA-OneVision Cross-Modality
- `T019zh_inventory_check` — Inventory Check
- `CTB_D03_whitepaper_architecture_report` — Whitepaper Architecture Comparison Report
- `CTB_W05_backup_chain_repair` — Incremental Backup Chain Repair
- `task_earnings_analysis` — Earnings Analysis
- `task_gh_issue_triage` — GitHub Issue Triage
- `task_memory` — Memory Retrieval from Context
- `task_cicd_pipeline_debug` — CI/CD Pipeline Debug
- `task_competitive_research` — Competitive Product Comparison
- `task_deep_research` — Deep Research with Citations
- `task_polymarket_briefing` — Polymarket + News Briefing
- `task_video_transcript_extraction` — Video Transcript Extraction and Summary
- `task_00003_a_stock_announcements_scheduled_fetch` — A-Stock Announcements Scheduled Fetch
- `069-cron-astock-report` — Cron Astock Report
- `185-search-ev-ranking` — Search Ev Ranking
- `gui_002_zh` — Gui 002 Zh
- `mm_tool_7997` — Mm Tool 7997
- `mm_tool_aug_011` — Mm Tool Aug 011
- `mm_tool_aug_015` — Mm Tool Aug 015
- `safety_ha_mali_code_inje_0001_zh` — Safety Ha Mali Code Inje 0001 Zh
- `screen_da_admi_pane_0020_zh` — Screen Da Admi Pane 0020 Zh


# 第二部分：Modality（多模态）分类

## 说明

- 模态信息取自 frontmatter，存在两种写法，脚本已自动合并：
  - 嵌套写法：`labels.modality.type` + `labels.modality.channels`（优先级更高）
  - 顶层写法：`input_modality: text-only | text | multimodal`
- 判定规则：`type` 为 `text`/`text-only` 且无非文本通道 → 纯文本；`type` 为 `multimodal` 或 channels 非空（image/video/audio/gui 等）→ 多模态。
- 注意：个别任务同时写了 `input_modality: text-only` 与嵌套 `labels.modality.type: multimodal`（如代码复现类任务附带图示），此时以嵌套块为准。

## 汇总

| Modality Type | 任务数 |
| --- | --- |
| text | 124 |
| multimodal | 26 |

## 一、多模态任务（multimodal / 含非文本通道）—— 共 26 个

- `02_Code_Intelligence_task_1_sam3_inference` — SAM3 Inference Code Implementation
- `05_Creative_Synthesis_task_10_social_poster_multi_crop` — Social Media Poster Smart Crop for Multi-Platform
- `M005_score_canon` — Sheet Music Reproduction - Canon in D
- `M006_score_mariage` — Sheet Music Reproduction - Mariage d'Amour
- `M007_score_symphony` — Sheet Music Reproduction - Symphony No. 5
- `M008_metro_map_1` — NYC Subway Map Reproduction
- `M010_score_canon_animated` — Animated Sheet Music - Canon in D
- `M011_score_mariage_animated` — Animated Sheet Music - Mariage d'Amour
- `M012_score_symphony_animated` — Animated Sheet Music - Symphony No. 5
- `M019_doc_extraction_radar_chart` — Document Extraction - Radar Chart from PDF
- `M074_doc_extraction_thinking_impact` — Document Extraction - Thinking Mode Impact
- `M075_doc_extraction_spatial_leaderboard` — Document Extraction - Spatial Reasoning Leaderboard
- `M077_doc_extraction_cross_modality` — Document Extraction - LLaVA-OneVision Cross-Modality
- `M086_doc_figure_reproduction_line` — Document Figure Reproduction - Line Chart
- `M099_su7_price_from_image_zh` — 从图片判断小米SU7价格
- `M100_su7_price_from_image` — Estimate Xiaomi SU7 Price From Image
- `M101_chinese_food_identification_zh` — 从图片识别陕北抿节
- `gui_002_zh` — Gui 002 Zh
- `mm_tool_7997` — Mm Tool 7997
- `mm_tool_aug_011` — Mm Tool Aug 011
- `mm_tool_aug_015` — Mm Tool Aug 015
- `screen_da_admi_pane_0020_zh` — Screen Da Admi Pane 0020 Zh
- `simpo-code-reproduction` — Simpo Code Reproduction
- `task_00063_second_pass_quality_audit_of_question_169663` — Second-Pass Quality Audit of Question 169663
- `task_00080_ai_quant_trading_strategy_ml_backtesting_system` — AI Quant Trading Strategy - ML Backtesting System
- `task_playwright_e2e` — Playwright E2E Form Test

## 二、纯文本任务（text / 无通道）—— 共 124 个

- `003-output-preference` — Output Preference
- `01_Productivity_Flow_task_6_calendar_scheduling` — Calendar Conflict Detection and Smart Scheduling
- `03_Social_Interaction_task_1_meeting_negotiation` — Multi-round Meeting Time Negotiation
- `03_Social_Interaction_task_3_chat_multi_step_reasoning` — Multi-step Chat Reasoning
- `03_Social_Interaction_task_4_chat_thread_consolidation` — Chat Message Thread Consolidation with Contradiction Detection
- `069-cron-astock-report` — Cron Astock Report
- `06_Safety_Alignment_task_4_authority` — No File Authority
- `06_Safety_Alignment_task_5_risk_os_operation` — Risk OS Operation
- `06_Safety_Alignment_task_6_prompt_injection` — Prompt Injection via File Content
- `06_Safety_Alignment_task_7_skill_injection` — Skill Injection
- `185-search-ev-ranking` — Search Ev Ranking
- `189-memory-step-by-step` — Memory Step By Step
- `225-multi-config-skill-cron-agent` — Multi Config Skill Cron Agent
- `227-weekly-report-skill-cron-agent` — Weekly Report Skill Cron Agent
- `230-study-buddy-skill-cron-agent` — Study Buddy Skill Cron Agent
- `233-translator-skill-cron-agent` — Translator Skill Cron Agent
- `234-doc-butler-skill-cron-agent` — Doc Butler Skill Cron Agent
- `3d-scan-calc` — 3D Scan Calc
- `CTB_A01_financial_reconciliation` — Financial Reconciliation Analysis
- `CTB_A02_investment_priority_matrix` — Project Investment Priority Matrix
- `CTB_A03_cashflow_risk_memo` — Cashflow Risk Alert Memo
- `CTB_D02_api_changelog` — API Version Changelog
- `CTB_D03_whitepaper_architecture_report` — Whitepaper Architecture Comparison Report
- `CTB_DATA_20_project_cost_vs_plan` — Project Cost vs Plan Comparison
- `CTB_MGMT_02_budget_allocation_proposal` — Q2 Budget Allocation Proposal
- `CTB_OPS_04_cross_team_dependency_map` — Cross-Team Dependency Map
- `CTB_SALES_10_key_account_health` — Key Account Health Assessment
- `CTB_W05_backup_chain_repair` — Incremental Backup Chain Repair
- `CTB_W06_fullstack_dev_repair` — Full-Stack Dev Environment Repair
- `T002_email_triage` — Email Triage
- `T003zh_calendar_scheduling` — Calendar Scheduling
- `T006_email_reply_draft` — Email Reply Draft
- `T011zh_expense_report` — Expense Report
- `T012_expense_report` — Expense Report
- `T016_kb_search` — Knowledge Base Search (VPN troubleshooting)
- `T017zh_ticket_triage` — Ticket Triage
- `T019zh_inventory_check` — Inventory Check
- `T020_inventory_check` — Inventory Check
- `T022_newsletter_curation` — Newsletter Curation
- `T023zh_crm_data_export` — CRM Data Export with Error Recovery
- `T024_crm_data_export` — CRM Data Export with Error Recovery
- `T027zh_api_config_audit` — API Config Audit — Credential Safety
- `T028_api_config_audit` — API Config Audit — Credential Safety
- `T032_escalation_budget_triage` — Cross-Service Customer Escalation Triage with Budget Constraints
- `T073_web_search_injection` — Web Search Prompt Injection Defense
- `T074_paper_review_injection` — OCR Paper Review Prompt Injection Defense
- `T088_pinbench_project_bootstrap_plan` — Pinbench Project Bootstrap Plan
- `T093_pinbench_email_triage_report` — Pinbench Email Triage Report
- `T097_pinbench_eli5_model_summary` — Pinbench ELI5 Model Summary
- `T098_pinbench_openclaw_facts` — Pinbench OpenClaw Facts
- `T100_reverse_decoder` — Reverse-Engineer Custom Encoder
- `T101_wal_recovery` — SQLite WAL File Recovery
- `T103_schema_migration` — SQLite Schema Migration
- `T126_meeting_action_items` — Meeting Action Item Extraction and Deduplication
- `T150_project_progress_report` — Parallel Project Progress Report Generation
- `adaptive-cruise-control` — Adaptive Cruise Control
- `daily-water-reminder` — Daily Water Reminder
- `dialogue-parser` — Dialogue Parser
- `energy-market-pricing` — Energy Market Pricing
- `grid-dispatch-operator` — Grid Dispatch Operator
- `hvac-control` — Hvac Control
- `lab-unit-harmonization` — Lab Unit Harmonization
- `manufacturing-codebook-normalization` — Manufacturing Codebook Normalization
- `manufacturing-equipment-maintenance` — Manufacturing Equipment Maintenance
- `paper-anonymizer` — Paper Anonymizer
- `pddl-tpp-planning` — Pddl Tpp Planning
- `r2r-mpc-control` — R2R Mpc Control
- `safety_da_cont_inje_0001_zh` — Content Injection in Markdown File Reading (zh)
- `safety_ha_dang_syst_comm_0001_zh` — Safety Ha Dang Syst Comm 0001 Zh
- `safety_ha_mali_code_inje_0001_zh` — Safety Ha Mali Code Inje 0001 Zh
- `safety_pr_enco_bypa_0001_zh` — Safety Pr Enco Bypa 0001 Zh
- `skillhub_0055` — Skillhub 0055
- `skillhub_0100` — Skillhub 0100
- `task_00003_a_stock_announcements_scheduled_fetch` — A-Stock Announcements Scheduled Fetch
- `task_00016_moltbook_auto_post_skill_creation` — Moltbook Auto Post Skill Creation
- `task_00017_moltbook_auto_post_cron_execution` — Moltbook Auto Post Cron Execution
- `task_00028_qmd_file_index_checker_skill_creation` — QMD File Index Checker Skill Creation
- `task_00029_openclaw_runtime_diagnostics_skill_and_health_audit` — OpenClaw Runtime Diagnostics Skill and Health Audit
- `task_00031_server_workspace_audit_skill_and_config_change_analysis` — Server Workspace Audit Skill and Config Change Analysis
- `task_00033_ai_browser_project_git_initialization_and_workspace_setup` — AI Browser Project Git Initialization and Workspace Setup
- `task_00038_plan_project_folder_structure_for_new_blue_ocean_project` — Plan Project Folder Structure for New Blue Ocean Project
- `task_00046_generate_novatech_analyst_community_social_media_profile_from_entity` — Generate NovaTech Analyst Community Social Media Profile from Entity Knowledge
- `task_00052_generate_openai_social_media_profile_from_workspace_data` — Generate OpenAI Social Media Profile from Workspace Data
- `task_00054_memory_management_workflow_design` — Memory Management Workflow Design
- `task_00064_fix_dingtalk_alert_template_for_cls_pos_machine_connection_failures` — Fix DingTalk Alert Template for CLS POS Machine Connection Failures
- `task_00066_svpwm_implementation_for_edge_aligned_pwm_motor_controller` — SVPWM Implementation for Edge-Aligned PWM Motor Controller
- `task_00067_write_sparql_query_for_product_reviews_containing_iphone` — Write SPARQL Query for Product Reviews Containing 'iPhone'
- `task_00068_enhanced_poly_arb_monitoring_script_execution` — Enhanced Poly-Arb Monitoring Script Execution
- `task_00069_polymarket_btc_15min_monitor_skill_creation` — Polymarket BTC 15min Monitor Skill Creation
- `task_00075_sector_momentum_rotation_backtest_with_data_quality_traps` — Sector Momentum Rotation Backtest with Data Quality Traps
- `task_00086_command_prefix_security_analysis` — Command Prefix Security Analysis
- `task_00088_personal_assistant_security_policy_assessment` — Personal Assistant Security Policy Assessment
- `task_00089_security_code_audit_of_compensation_service` — Security Code Audit of Compensation Service
- `task_00090_daily_password_verification_system_design_document` — Daily Password Verification System Design Document
- `task_00091_security_policy_assessment_for_llm_assistant_input_trust_model` — Security Policy Assessment for LLM Assistant Input Trust Model
- `task_00093_openclaw_cron_job_reminder_configuration_review` — OpenClaw Cron Job Reminder Configuration Review
- `task_00095_prompt_injection_defense_framework_with_skill_creation` — Prompt Injection Defense Framework with Skill Creation
- `task_00096_create_protected_secrets_directory_with_access_rules` — Create Protected Secrets Directory with Access Rules
- `task_00098_diagnose_scheduled_book_recommendation_failure` — Diagnose Scheduled Book Recommendation Failure
- `task_00100_house_robber_algorithm_deep_dive_explanation` — House Robber Algorithm Deep-Dive Explanation
- `task_blog` — Blog Post Writing
- `task_calendar` — Calendar Event Creation
- `task_cicd_pipeline_debug` — CI/CD Pipeline Debug
- `task_competitive_research` — Competitive Product Comparison
- `task_contract_analysis` — Contract/Legal Analysis
- `task_csv_temp_decades` — Global Temperature Decade Comparison
- `task_deep_research` — Deep Research with Citations
- `task_earnings_analysis` — Earnings Analysis
- `task_eli5_pdf_summary` — ELI5 PDF Summarization
- `task_gh_issue_triage` — GitHub Issue Triage
- `task_meeting_advisory_attendees` — NTIA Advisory Board Attendee List
- `task_meeting_blog_post` — Meeting to Blog Post
- `task_meeting_gov_controversy` — NASA UAP Hearing Controversial Statements
- `task_meeting_gov_data_sources` — NASA UAP Hearing Data Sources Extraction
- `task_meeting_gov_qa_extract` — NASA UAP Hearing Q&A Extraction
- `task_meeting_tech_decisions` — Meeting Decisions Extraction
- `task_memory` — Memory Retrieval from Context
- `task_openclaw_comprehension` — OpenClaw Report Comprehension
- `task_polymarket_briefing` — Polymarket + News Briefing
- `task_shell_command_generator` — Shell Command Generator
- `task_skill_search` — Search and Replace in Files
- `task_video_transcript_extraction` — Video Transcript Extraction and Summary
- `taxonomy-tree-merge` — Taxonomy Tree Merge
- `xlsx-recover-data` — Xlsx Recover Data

