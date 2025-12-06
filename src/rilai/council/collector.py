"""Assessment collector for council deliberation."""

from dataclasses import dataclass, field

from rilai.agencies.messages import AgencyAssessment, AgentAssessment
from rilai.agencies.runner import AgencyRunResult


@dataclass
class CollectedAssessments:
    """Organized assessments for council synthesis."""

    by_agency: dict[str, AgencyAssessment] = field(default_factory=dict)
    all_agents: list[AgentAssessment] = field(default_factory=list)
    total_agencies: int = 0
    highest_urgency: int = 0

    def get_top_agents(self, n: int = 5) -> list[AgentAssessment]:
        """Get top N agents by salience score."""
        sorted_agents = sorted(
            [a for a in self.all_agents if a.salience is not None],
            key=lambda a: a.salience.raw_score if a.salience else 0,
            reverse=True,
        )
        return sorted_agents[:n]


class AssessmentCollector:
    """Collects and organizes assessments from all agencies."""

    def collect(self, run_result: AgencyRunResult) -> CollectedAssessments:
        """Collect assessments from agency run results.

        Args:
            run_result: Results from running all agencies

        Returns:
            CollectedAssessments organized for synthesis
        """
        collected = CollectedAssessments()
        collected.total_agencies = len(run_result.assessments) + run_result.agencies_failed

        for assessment in run_result.assessments:
            collected.by_agency[assessment.agency_id] = assessment

            # Track highest urgency
            if assessment.agency_u_max > collected.highest_urgency:
                collected.highest_urgency = assessment.agency_u_max

            # Collect all agent assessments
            for sub in assessment.sub_assessments:
                collected.all_agents.append(sub)

        return collected
