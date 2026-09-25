// An agent's "What it does" tab: the same page the setup sits on, read as prose first.
// Everything here is written copy — one card per role describing the work it is given,
// what it reads, what it hands back and where it refuses to go — plus the facts the
// summary already carries (pipeline position, standards domain, permissions, model).
// The English strings are the translation keys, as everywhere else in the UI.
import type { AgentSummary } from "../api/client";
import { useT } from "../i18n";
import { AgentAvatar } from "../components/AgentAvatar";

type About = {
  /** one paragraph: the job, in the words a person would use */
  what: string;
  /** where in a development it is woken up */
  when: string;
  reads: string[];
  produces: string[];
  /** the boundaries it is told to keep — what it hands to another agent instead */
  never: string[];
};

const ABOUT: Record<string, About> = {
  po: {
    what: "The Product Owner turns the request into a backlog: epics, stories and tasks. It reads the repository lightly — the tree, the manifests, the README — so the backlog fits the product that already exists, but it decides nothing about technology or files. A task is one piece of work a single specialist can finish and a tester can verify.",
    when: "First, as soon as a development starts. Its backlog waits at the first gate for you; once approved it is mirrored into Jira and the Architect takes over.",
    reads: [
      "Your request, in your words",
      "The repository at a glance: tree, manifests, README",
      "Your feedback, when you rejected the previous backlog",
      "The product standards and the core rules",
    ],
    produces: [
      "Epics, stories and tasks, ordered so that what others depend on comes first",
      "A one- or two-sentence description per task saying what done looks like",
      "The Jira issues, once you approve the backlog",
    ],
    never: [
      "Choosing technology, libraries or files — that is the Architect's decision",
      "Writing a task that needs two specialists: it splits it in two and says which comes first",
    ],
  },
  architect: {
    what: "The Architect reads the approved backlog together with the repository and decides how the work will be done: the project profile (the exact commands that build, test and run it), the decisions worth writing down, and the ordered phases — one phase per backlog task, each tagged with the domain whose specialist implements it.",
    when: "After you approve the backlog. Its plan waits at the architecture gate; once approved the specialists start on phase one.",
    reads: [
      "The approved backlog",
      "The repository: manifests, lockfiles, CI configuration, README",
      "The seed profile, whose model routing it must keep as given",
      "Your feedback, when you rejected the previous plan",
      "The architecture standards and the core rules",
    ],
    produces: [
      "The build, test and run commands — preferring the ones CI already runs",
      "Architecture decisions: one sentence each, saying the choice and the reason",
      "Ordered phases with the files each one will touch, backend contracts before the front-ends that use them",
    ],
    never: [
      "Choosing models — routing always comes from the project's seed profile",
      "Inventing a command the repository does not support: it says what is missing instead",
      "Guessing past an ambiguity that would change the design — it stops and asks at the gate",
    ],
  },
  backend: {
    what: "The Backend specialist implements one phase at a time: services, HTTP and RPC APIs, data models and migrations, background jobs and integrations. It returns the complete contents of every file it creates or changes, and the change goes through the build gate before the next phase begins. Phases with no specialist domain of their own — general work and documentation — also come here.",
    when: "During development, on every phase the Architect tagged backend (and on general and docs phases).",
    reads: [
      "The phase it was given, and only that phase",
      "The files the phase names, and the project's build and test commands",
      "The build output, when its previous attempt failed the gate",
      "The backend standards and the core rules",
    ],
    produces: [
      "The complete new contents of each file it touches",
      "A summary saying what was done, what was not, and what it was unsure about",
      "The Jira transition and the work log on the task it implemented",
    ],
    never: [
      "Touching front-end code: it finishes the backend part and describes the missing piece for the Architect",
      "Refactoring beyond the phase, or weakening a check to make the build gate green",
    ],
  },
  designer: {
    what: "The Designer decides what each screen is before anyone builds one: what a person comes there to do, what sits where, which states it has and what every control does. It draws each screen as a self-contained HTML mock so you approve a picture rather than a paragraph. The Web and Mobile specialists then build the same screen from the same decision, which is what keeps the two halves of a product looking like one product.",
    when: "After you approve the plan, and only when that plan has a web or mobile phase in it. The backend phases are built while its screens wait for you; the first UI phase stops until they are approved.",
    reads: [
      "The approved backlog and the plan's phases",
      "The design standards and the core rules",
      "Its previous screens, and your reason when you sent one back",
    ],
    produces: [
      "One entry per screen: purpose, layout, components, states and interactions",
      "An HTML mock of each screen, drawn in its ordinary state",
      "The few principles that hold across every screen",
    ],
    never: [
      "Writing code or files — it has no permission to, and the specialists build from what it wrote",
      "Inventing a screen the backlog does not ask for: it says so in the notes instead",
      "Choosing colours, fonts or a component library — that follows the stack the Architect chose",
    ],
  },
  web_ui: {
    what: "The Web UI specialist implements web front-end phases: pages, components, client state, styling, accessibility and front-end tests. It works against the contract the plan describes and keeps every call to the server in one client module.",
    when: "During development, on every phase the Architect tagged web.",
    reads: [
      "The phase it was given, and only that phase",
      "The files the phase names, the design tokens and the existing components",
      "The contract the backend phase defined, from the architecture decisions",
      "The web standards and the core rules",
    ],
    produces: [
      "The complete new contents of each file it touches",
      "A summary naming any endpoint it needed that does not exist yet",
      "The Jira transition and the work log on the task it implemented",
    ],
    never: [
      "Adding or changing a server endpoint — it says exactly which one is missing so the Architect can add a backend phase",
      "Hard-coding a colour, or shipping a control that the keyboard cannot reach",
    ],
  },
  mobile_ui: {
    what: "The Mobile UI specialist implements mobile phases: screens, navigation, platform APIs, offline and sync state, and mobile tests. It prefers the platform's conventions over web patterns.",
    when: "During development, on every phase the Architect tagged mobile.",
    reads: [
      "The phase it was given, and only that phase",
      "The app's structure: features, shared core, the API client",
      "The backend contracts it has to rely on",
      "The mobile standards and the core rules",
    ],
    produces: [
      "The complete new contents of each file it touches",
      "A summary naming the backend contracts it relied on and the ones that are missing",
      "The Jira transition and the work log on the task it implemented",
    ],
    never: [
      "Changing server code",
      "Putting business logic in a screen, or a token anywhere but the platform's secure store",
    ],
  },
  qa: {
    what: "QA does three jobs. After every phase it reviews the specialist's diff against the standards that specialist was told to follow, and reports each breach with the file, the line and a concrete fix. When the branch is complete it proposes the test cases that would prove the change works — for you to add to, remove from and approve. Then it writes automated tests for exactly the approved list.",
    when: "After each phase for the standards review, and once the whole branch is built for the test cases and the tests.",
    reads: [
      "The phase diff, together with the standards sections that phase was given",
      "The branch diff, the plan and the backlog it implements",
      "The project's existing test layout, frameworks and runners",
      "The approved list of test cases — no more, no fewer",
    ],
    produces: [
      "Standards violations, each marked blocking or advisory, with a fix",
      "At most fifteen proposed test cases, each in a sentence or two",
      "The test files themselves, complete, in the project's own layout",
      "A Jira bug for each defect it finds, closed once the fix passes",
    ],
    never: [
      "Inventing a rule that is not in the standards, or a finding to have something to report",
      "Writing a test for a case you did not approve",
    ],
  },
  devops: {
    what: "DevOps does the infrastructure phases — Dockerfiles, compose files, CI workflows, deployment and environment configuration — and, at the end of a development, writes the pull request: a title and a body that say what changed, why, and how it was tested, from the approved plan and the job history.",
    when: "During development on infra phases, and at the end of every development for the pull request.",
    reads: [
      "The phase it was given, for infrastructure work",
      "The factual draft assembled from the plan and the job history",
      "The branch diff: everything that actually changed",
      "The devops standards and the core rules",
    ],
    produces: [
      "Packaging and pipeline files, with configuration through environment variables",
      "A pull request title under seventy characters and a Markdown body listing the phases",
      "A note on what a person still has to do by hand — create a secret, open a port",
      "The outcome commented on the Jira stories",
    ],
    never: [
      "Inventing anything that is not in the draft or the diff",
      "Committing a secret, or changing application code beyond what packaging needs",
    ],
  },
  supervisor: {
    what: "The Supervisor reads exactly what you would read at a gate — the proposal and the history behind it — and recommends approve or reject, with its confidence, the risk it sees and short concrete reasons. When a phase fails the build gate there is nothing to approve: it decides whether the specialist tries again, the plan is redone, or a human is needed.",
    when: "At every human gate, and whenever a phase fails the build gate.",
    reads: [
      "The material at the gate: a backlog, an architecture, a standards review, test cases or the written tests",
      "The job history so far, and the original request",
      "The build output, when a phase failed the gate",
      "The standards of every domain and the core rules",
    ],
    produces: [
      "Approve or reject, with a confidence between 0 and 1",
      "A risk reading: low, medium or high, and at most five reasons",
      "Feedback the agent can act on, when it rejects",
      "After a failed build: fix, replan or ask a human",
    ],
    never: [
      "Inventing objections — it prefers approving with medium risk noted",
      "Deciding in your place: the recommendation is yours to take or leave, unless you turned auto-approval on",
    ],
  },
};

export function AgentAboutTab({ agent }: { agent: AgentSummary }) {
  const tx = useT();
  const about = ABOUT[agent.role];
  if (!about) return null;
  return (
    <div className="about">
      <div className="card about-lead">
        <AgentAvatar role={agent.role} className="lg" />
        <div>
          <p className="lead">{tx(about.what)}</p>
          <p className="muted small">
            <strong>{tx("When it works")}:</strong> {tx(about.when)}
          </p>
        </div>
      </div>

      <div className="grid-3 about-lists">
        <List title={tx("What it reads")} items={about.reads.map((r) => tx(r))} tone="in" />
        <List
          title={tx("What it hands back")}
          items={about.produces.map((r) => tx(r))}
          tone="out"
        />
        <List
          title={tx("What it leaves to others")}
          items={about.never.map((r) => tx(r))}
          tone="no"
        />
      </div>

      <div className="card">
        <div className="card-head" style={{ padding: 0, border: 0, marginBottom: 12 }}>
          <h3>{tx("How it is set up right now")}</h3>
        </div>
        <dl className="kv about-facts">
          <dt>{tx("Model")}</dt>
          <dd className="mono">
            {agent.effective_model}
            <span className="faint"> · {agent.effective_provider}</span>
          </dd>
          <dt>{tx("Thinking depth")}</dt>
          <dd>{agent.thinking_depth}</dd>
          <dt>{tx("Standards")}</dt>
          <dd>
            {agent.standards_domain === "*" ? tx("all domains") : tx(agent.standards_domain)}
            <span className="faint"> · {tx("plus the shared rules")}</span>
          </dd>
          <dt>{tx("Permissions")}</dt>
          <dd>
            {agent.permissions.length === 0 ? (
              <span className="muted">{tx("none")}</span>
            ) : (
              <span className="row" style={{ gap: 4 }}>
                {agent.permissions.map((p) => (
                  <span key={p} className="tag" style={{ marginLeft: 0 }}>
                    {p}
                  </span>
                ))}
              </span>
            )}
          </dd>
        </dl>
        <p className="muted small" style={{ marginTop: 10 }}>
          {tx(
            "Thinking depth and permissions come from the project you pick under Setup; the model is the one this agent is pinned to, on every project.",
          )}
        </p>
      </div>
    </div>
  );
}

function List({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  return (
    <div className="card flush">
      <div className="card-head">
        <h3>{title}</h3>
      </div>
      <div className="card-body">
        <ul className={`ticks ${tone}`}>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
