# Group Functions Autopilot guardrails, evaluated by the Agent Governance Toolkit (ACS runtime + OPA).
#
# The host asks this policy before a run starts, before and after every model call, before and after
# every tool call (MCP tools, skill scripts, model-written code, sub-agents) and before the final answer
# is published. Each rule adds a finding; the most severe finding wins: deny > escalate > transform > warn.
# Anything without a finding is allowed. Tunable values live in data.autopilot (the Parameters tab).
package guardrails

import rego.v1

cfg := data.autopilot

point := input.intervention_point

snap := input.snapshot

target := input.policy_target.value

tool := object.get(input, ["tool", "name"], "")

access := object.get(input, ["tool", "access"], "")

role := object.get(snap, ["agent", "role"], "orchestrator")

usage(name) := object.get(snap, ["usage", name], 0)

finding(decision, reason, message) := {"decision": decision, "reason": reason, "message": message}

matches_any(name, patterns) if {
	some pattern in patterns
	glob.match(pattern, [], name)
}

# Deployment names such as gpt-5.4 contain dots, so "*" must span them.
matches_model(name, patterns) if {
	some pattern in patterns
	glob.match(pattern, ["/"], name)
}

severity := {"deny": 4, "escalate": 3, "transform": 2, "warn": 1}

top := max({severity[f.decision] | some f in findings})

default verdict := {"decision": "allow"}

verdict := [f | some f in findings; severity[f.decision] == top][0] if count(findings) > 0

# METADATA
# title: Pause every AI teammate
# description: Set paused to true in Parameters and no new run can start, anywhere in the fleet.
# custom:
#   id: fleet.paused
#   decision: deny
#   points: [agent_startup]
findings contains finding("deny", "fleet.paused", "All AI teammates are paused by the operator.") if {
	point == "agent_startup"
	cfg.paused == true
}

# METADATA
# title: Blocked tools
# description: Tools matching tools.blocked never run, whatever the skill, delegation or approval says.
# custom:
#   id: tools.blocked
#   decision: deny
#   points: [pre_tool_call]
findings contains finding("deny", "tools.blocked", sprintf("%s is blocked by guardrail policy.", [tool])) if {
	point == "pre_tool_call"
	matches_any(tool, cfg.tools.blocked)
}

# METADATA
# title: Tools that always need a person
# description: Tools matching tools.require_approval go to a person even when a skill pre-approves them.
# custom:
#   id: tools.require_approval
#   decision: escalate
#   points: [pre_tool_call]
findings contains finding("escalate", "tools.require_approval", sprintf("%s always needs a person's approval.", [tool])) if {
	point == "pre_tool_call"
	matches_any(tool, cfg.tools.require_approval)
}

# METADATA
# title: Approving spend needs a person
# description: An approve decision on a purchasing record is never taken autonomously.
# custom:
#   id: spend.approve
#   decision: escalate
#   points: [pre_tool_call]
findings contains finding("escalate", "spend.approve", "Approving spend always needs a person's go-ahead.") if {
	point == "pre_tool_call"
	endswith(tool, ".approve_reject")
	lower(object.get(target, "action", "")) == "approve"
}

# METADATA
# title: Large amounts need a person
# description: Any amount, total, price or value above limits.max_amount goes to a person.
# custom:
#   id: spend.amount
#   decision: escalate
#   points: [pre_tool_call]
findings contains finding("escalate", "spend.amount", sprintf("%v is above the %v limit for autonomous changes.", [value, cfg.limits.max_amount])) if {
	point == "pre_tool_call"
	access == "write"
	some key, value in target
	lower(key) in {"amount", "total", "total_amount", "price", "unit_price", "value", "cost"}
	is_number(value)
	value > cfg.limits.max_amount
}

# METADATA
# title: Sub-agents only read
# description: Research sub-agents may never change a system.
# custom:
#   id: writes.subagent
#   decision: deny
#   points: [pre_tool_call]
findings contains finding("deny", "writes.subagent", "Sub-agents can only read.") if {
	point == "pre_tool_call"
	role == "subagent"
	access == "write"
}

# METADATA
# title: Change budget per run
# description: After limits.max_writes changes in one run, every further change needs a person.
# custom:
#   id: writes.budget
#   decision: escalate
#   points: [pre_tool_call]
findings contains finding("escalate", "writes.budget", sprintf("This run already made %v changes; more need a person.", [usage("writes")])) if {
	point == "pre_tool_call"
	access == "write"
	usage("writes") >= cfg.limits.max_writes
}

# METADATA
# title: Tool-call budget per run
# description: A run stops calling tools after limits.max_tool_calls calls.
# custom:
#   id: run.tool_budget
#   decision: deny
#   points: [pre_tool_call]
findings contains finding("deny", "run.tool_budget", sprintf("This run reached its %v tool-call budget.", [cfg.limits.max_tool_calls])) if {
	point == "pre_tool_call"
	usage("tool_calls") >= cfg.limits.max_tool_calls
}

# METADATA
# title: Code execution switch
# description: Model-written Python runs only while code.enabled is true (and in sub-agents only with code.subagents).
# custom:
#   id: code.disabled
#   decision: deny
#   points: [pre_tool_call]
findings contains finding("deny", "code.disabled", "Running model-written code is switched off by the operator.") if {
	point == "pre_tool_call"
	tool == "code.run_python"
	not cfg.code.enabled
}

findings contains finding("deny", "code.disabled", "Sub-agents may not run model-written code.") if {
	point == "pre_tool_call"
	tool == "code.run_python"
	role == "subagent"
	not cfg.code.subagents
}

# METADATA
# title: Code must parse
# description: A program that does not parse cannot be inspected, so it does not run.
# custom:
#   id: code.syntax
#   decision: deny
#   points: [pre_tool_call]
findings contains finding("deny", "code.syntax", sprintf("The program does not parse (%v); fix it and try again.", [snap.code.error])) if {
	point == "pre_tool_call"
	tool == "code.run_python"
	snap.code.syntax_ok == false
}

# METADATA
# title: Approved imports only
# description: Model-written Python may import only the modules in code.allowed_imports.
# custom:
#   id: code.imports
#   decision: deny
#   points: [pre_tool_call]
findings contains finding("deny", "code.imports", sprintf("Imports not allowed by policy: %v. Use only: %v.", [concat(", ", sort(blocked)), concat(", ", sort(cfg.code.allowed_imports))])) if {
	point == "pre_tool_call"
	tool == "code.run_python"
	blocked := {name | some name in snap.code.imports; not name in cfg.code.allowed_imports}
	count(blocked) > 0
}

# METADATA
# title: Dangerous calls
# description: Dynamic code, interpreter internals and process control (code.blocked_calls, code.blocked_attributes).
# custom:
#   id: code.calls
#   decision: deny
#   points: [pre_tool_call]
findings contains finding("deny", "code.calls", sprintf("Calls not allowed by policy: %v.", [concat(", ", sort(blocked))])) if {
	point == "pre_tool_call"
	tool == "code.run_python"
	blocked := {name | some name in snap.code.calls; name in cfg.code.blocked_calls} | {name | some name in snap.code.attributes; name in cfg.code.blocked_attributes}
	count(blocked) > 0
}

# METADATA
# title: Program size
# description: Programs longer than code.max_chars characters are refused.
# custom:
#   id: code.size
#   decision: deny
#   points: [pre_tool_call]
findings contains finding("deny", "code.size", sprintf("The program is %v characters; the limit is %v.", [count(target.code), cfg.code.max_chars])) if {
	point == "pre_tool_call"
	tool == "code.run_python"
	count(target.code) > cfg.code.max_chars
}

# METADATA
# title: Code time limit
# description: A requested time limit above code.max_timeout_seconds is lowered to the maximum.
# custom:
#   id: code.timeout
#   decision: transform
#   points: [pre_tool_call]
findings contains {
	"decision": "transform",
	"reason": "code.timeout",
	"message": sprintf("Time limit lowered to %v seconds.", [cfg.code.max_timeout_seconds]),
	"transform": {"path": "$policy_target.timeout_seconds", "value": cfg.code.max_timeout_seconds},
} if {
	point == "pre_tool_call"
	tool == "code.run_python"
	object.get(target, "timeout_seconds", 0) > cfg.code.max_timeout_seconds
}

# METADATA
# title: Sub-agent fan-out
# description: At most limits.max_subagents Copilot sub-agents run at once in a run.
# custom:
#   id: delegate.fanout
#   decision: deny
#   points: [pre_tool_call]
findings contains finding("deny", "delegate.fanout", sprintf("At most %v sub-agents may run at once.", [cfg.limits.max_subagents])) if {
	point == "pre_tool_call"
	tool == "agent.task"
	usage("subagents") >= cfg.limits.max_subagents
}

# METADATA
# title: Turn budget
# description: A run gets at most limits.max_turns model turns.
# custom:
#   id: model.turns
#   decision: deny
#   points: [pre_model_call]
findings contains finding("deny", "model.turns", sprintf("The run reached its %v-turn budget.", [cfg.limits.max_turns])) if {
	point == "pre_model_call"
	target.role == "orchestrator"
	target.turn > cfg.limits.max_turns
}

# METADATA
# title: Token budget
# description: A run stops once it has used limits.max_total_tokens tokens.
# custom:
#   id: model.tokens
#   decision: deny
#   points: [pre_model_call]
findings contains finding("deny", "model.tokens", sprintf("The run used %v tokens; the budget is %v.", [usage("total_tokens"), cfg.limits.max_total_tokens])) if {
	point == "pre_model_call"
	usage("total_tokens") > cfg.limits.max_total_tokens
}

# METADATA
# title: Approved models
# description: Only model deployments matching models.allowed may be called.
# custom:
#   id: model.allowed
#   decision: deny
#   points: [pre_model_call]
findings contains finding("deny", "model.allowed", sprintf("%v is not an approved model deployment.", [target.model])) if {
	point == "pre_model_call"
	not matches_model(target.model, cfg.models.allowed)
}

# METADATA
# title: Prompt-injection phrases
# description: Flags requests containing input.injection_phrases so an operator can review them.
# custom:
#   id: input.injection
#   decision: warn
#   points: [input]
findings contains finding("warn", "input.injection", sprintf("The request contains \"%v\", a common prompt-injection phrase.", [phrase])) if {
	point == "input"
	some phrase in cfg.input.injection_phrases
	contains(lower(target.text), lower(phrase))
}

redaction := concat("|", [sprintf("(?:%s)", [pattern]) | some pattern in cfg.redaction.patterns])

# METADATA
# title: Redact secrets in tool results
# description: Credentials matching redaction.patterns are removed before a result reaches the model.
# custom:
#   id: results.redact
#   decision: transform
#   points: [post_tool_call]
findings contains {
	"decision": "transform",
	"reason": "results.redact",
	"message": "Credentials were redacted from the tool result.",
	"transform": {"path": "$policy_target.text", "value": redacted},
} if {
	point == "post_tool_call"
	count(cfg.redaction.patterns) > 0
	redacted := regex.replace(target.text, redaction, cfg.redaction.replacement)
	redacted != target.text
}

# METADATA
# title: Redact secrets in answers
# description: The final answer never publishes credentials matching redaction.patterns.
# custom:
#   id: output.redact
#   decision: transform
#   points: [output]
findings contains {
	"decision": "transform",
	"reason": "output.redact",
	"message": "Credentials were redacted from the answer.",
	"transform": {"path": "$policy_target.text", "value": redacted},
} if {
	point == "output"
	count(cfg.redaction.patterns) > 0
	redacted := regex.replace(target.text, redaction, cfg.redaction.replacement)
	redacted != target.text
}
