---
id: replace-with-a-unique-task-id
name: Replace with a one-line task name
category: office
grading_type: llm_judge
timeout_seconds: 600
workspace_files: []
labels:
  capabilities:
    - Planning
  scenario: Office_Productivity/Task_Management
  complexity: L2
  environment: closed
  modality:
    type: text
---
## Prompt

Describe the deliverable and where it goes, for example "Write the summary to
`output/report.md`".  Everything the agent needs is either stated here or
declared in `workspace_files`.

## Grading Criteria

- [ ] The deliverable exists at the path the prompt names
- [ ] Replace this line with a criterion a judge can mark yes or no
- [ ] Replace this line with the next one

<!--
Fields that are easy to get wrong, and what the loader does with them:

grading_type   automated | llm_judge | hybrid
               automated runs the checks declared in the package; llm_judge sends
               the criteria below to the judge; hybrid needs both and keeps the
               automated half as the failure reason.

Grading Criteria
               A criterion must be a checkbox line ("- [ ] ...").  A plain
               bullet list is not read as a criterion at all, so an llm_judge
               task written that way reaches the judge with no rubric.

workspace_files
               One entry per fixture, "source" = path inside this package,
               "dest" = path inside the agent's workspace:
                 - source: assets/budget.xlsx
                   dest: input/budget.xlsx
               "source" must stay inside the package: no absolute path, no "..".
               Keep the list empty ([]) when the task has no attachments.

labels         capabilities / scenario / complexity / environment are required
               and feed the slice report; modality.type is optional.

Never put grading code, judge wording or fixture answers in the task text: the
task file is what the agent reads.
-->
