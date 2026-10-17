Feature: Budget pacing and guardrails
  As an ad operations engineer
  I want pacing measured against each campaign's spend curve
  So that overspend is caught while there is still time to act

  Scenario: Even-paced campaign at its midpoint is on track
    Given an even-paced campaign with a 10 day flight and a 100000 cent budget
    And 50000 cents spent by day 5
    When I evaluate pacing on day 5
    Then the pacing state is "on_track"
    And the target to date is 50000 cents
    And no guardrail alert is raised

  Scenario: Under-delivering campaign raises an under-pace alert
    Given an even-paced campaign with a 10 day flight and a 100000 cent budget
    And 30000 cents spent by day 5
    When I evaluate pacing on day 5
    Then the pacing state is "underspending"
    And the guardrail raises an "UNDER_PACE" alert

  Scenario: Hot campaign projects an overspend
    Given an even-paced campaign with a 10 day flight and a 100000 cent budget
    And 70000 cents spent by day 5
    When I evaluate pacing on day 5
    Then the pacing state is "overspending"
    And the projected overspend is 40000 cents
    And the guardrail raises a "PROJECTED_OVERSPEND" alert
