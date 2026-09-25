// Which agent owns which gate, and therefore who may act there.
//
// The same map lives in `slipwright/teams.py` and the server is the one that enforces it;
// this copy exists so a member is not shown a button that would come back 403. When the
// two disagree, the server wins and the page simply looks wrong for a moment.
import type { JobState, MyTeam, RoleName } from "./client";

export const GATE_AGENT: Partial<Record<JobState, RoleName>> = {
  awaiting_backlog_approval: "po",
  awaiting_architecture_approval: "architect",
  awaiting_design_approval: "designer",
  awaiting_review_approval: "qa",
  awaiting_test_approval: "qa",
  awaiting_deploy_approval: "devops",
  awaiting_decision: "supervisor",
};

export function agentForGate(state: JobState): RoleName | undefined {
  return GATE_AGENT[state];
}

/** Whether this person may approve, reject or edit what a development waits on.
 *
 * An owner (`team` absent, or not a member) may act everywhere. A member may act where
 * their own agent is waiting, and nowhere else -- including on a development that is not
 * waiting at all, which is the owner's to move. */
export function mayActAt(state: JobState, team: MyTeam | undefined): boolean {
  if (!team?.is_member) return true;
  const agent = agentForGate(state);
  return agent !== undefined && team.agents.includes(agent);
}

/** Whether this person owns the account rather than holding one of its agents. */
export function isOwner(team: MyTeam | undefined): boolean {
  return !team?.is_member;
}
