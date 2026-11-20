---
name: pawbench-datasets
description: Prepare and catalog PawBench evaluation datasets. Use when creating a task package, validating or registering a custom dataset, saving a built-in corpus slice, managing categories, or previewing mixed dataset selections before an evaluation job.
metadata:
  qwenpaw:
    requires:
      mcp: ["pawbench-eval"]
---

# PawBench Datasets

Use the configured `pawbench-eval` MCP server. Do not submit a job until the selector has been previewed with `pawbench_resolve_selector`. Do not quote grading rubrics, grading code, or fixture contents to the agent being evaluated.

## Prepare A Custom Dataset

1. Create a directory containing `tasks/<task-id>.md` and any declared `assets/` files. Give each task a unique `id` and a `## Prompt` section. Use front matter with `grading_type`, `timeout_seconds`, `workspace_files` (use `[]` when empty), and `labels` containing nonempty `capabilities`, `scenario`, `complexity`, and `environment`. Declare fixture paths relative to the package root in `workspace_files[].source`; do not include absolute paths, `..`, symlinks, `conftest.py`, `pytest.ini`, `tox.ini`, `sitecustomize.py`, `.pth`, or pytest test modules.
2. Add grading criteria and choose a grading type supported by the task loader (`automated`, `llm_judge`, or `hybrid`). Automated grading executes code on the evaluation host until a sandbox is deployed: do not upload or run grading code from untrusted authors.
3. Zip the directory. For ZIPs up to 512 KiB, base64-encode the ZIP bytes and call `pawbench_validate_dataset_package(archive_base64=...)`. Resolve every returned `items` error before calling `pawbench_create_custom_dataset(dataset_id=..., archive_base64=..., categories=...)`. The service attributes ownership to the bearer token; never supply or guess another owner.
4. For larger ZIPs, use the service's authenticated streaming `POST /v1/datasets/packages` route with the ZIP as the binary body and `id`, `name`, `categories`, `description` as query fields. Do not paste large ZIPs into an MCP call or send a local file path to the remote service. The HTTP route validates before registration and returns per-item errors. Do not log or expose bearer tokens or signed URLs.
5. Call `pawbench_describe_dataset` and verify the task count and labels. To group it, call `pawbench_manage_category` and `pawbench_assign_categories` using the registered dataset ID.

Copy `templates/task.md` (next to this file) as the task skeleton and keep its
shape. Two loader details decide whether a task actually grades:

- Each line under `## Grading Criteria` must be a checkbox, `- [ ] ...`. A plain
  bullet list is not read as a criterion, so an `llm_judge` task written that way
  reaches the judge with no rubric and scores nothing.
- A `workspace_files` entry has `source` (path inside the package) and `dest`
  (path inside the agent's workspace). Keep the list `[]` when the task has no
  attachments.

## Catalog A Builtin Slice

1. Call `pawbench_list_datasets` and `pawbench_list_categories` to inspect existing names and label distributions; call `pawbench_describe_dataset` for candidates.
2. For a reusable slice, call `pawbench_create_dataset(dataset_id=..., name=..., filter_spec=..., categories=[...])`. Supported filter fields include `task_ids`, `scenario`, `capability`, `complexity`, `environment`, `modality`, and `source`. Creation snapshots task IDs; check the returned task count before using it. Only the owner or admin may edit/delete an existing dataset.
3. Create or file categories with `pawbench_manage_category` and `pawbench_assign_categories`. Category names are normalized; use existing category names when possible.
4. Preview `{ "datasets": ["..."], "categories": ["..."] }` with `pawbench_resolve_selector`. Inspect `unknown_ids`, `task_count`, `duplicates_removed`, and `by_dataset`/`by_category`; resolve unexpected names or an empty selection before calling `pawbench_submit_job` with this selector.
