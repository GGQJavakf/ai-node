## ADDED Requirements

### Requirement: Daily startup plan summarizes active work

The assistant SHALL generate a daily startup plan from active WorkItems, next actions, stale sync markers, and high-priority evidence.

#### Scenario: Generate day start plan

- **WHEN** the user runs `/start day`
- **THEN** the assistant SHALL list recommended focus items
- **AND** it SHALL include the reason for each recommendation and the next concrete action.

### Requirement: Daily review generates a reusable work summary

The assistant SHALL generate a daily review draft from WorkItems and Evidence.

#### Scenario: Generate day review

- **WHEN** the user runs `/review day`
- **THEN** the assistant SHALL produce a concise Markdown draft with completed work, in-progress work, blockers, and recommended follow-ups.

#### Scenario: No evidence exists

- **WHEN** the user runs `/review day` with no recorded evidence
- **THEN** the assistant SHALL state that no evidence has been recorded
- **AND** it SHALL suggest commands to sync or record evidence.

### Requirement: Daily outputs distinguish facts from suggestions

Daily startup and review outputs SHALL distinguish completed facts from recommended next actions.

#### Scenario: Recommendation is generated

- **WHEN** the assistant recommends an action in `/start day`, `/continue`, or `/review day`
- **THEN** it SHALL label the item as a recommendation
- **AND** it SHALL not imply that the action has already been executed.
