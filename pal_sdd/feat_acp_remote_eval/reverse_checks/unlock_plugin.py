"""Pytest plugin: remove the serialization in memory, to see the case judge red."""
import pawbench.cpd.acp_remote_eval.service.grading as g

g._grade_automated_exclusively = lambda task, execution_result: g._grade_automated(
    task, execution_result
)
