// Writing to the agent on a step, under what the step was asked to do.
//
// Three things a person may want from the agent that holds a phase, and they are kept
// apart on purpose because they cost and change different things:
//
// - a question: answered beside the run by the same agent on its own model, and nothing
//   moves -- the answer arrives as an event and lands in the list;
// - an instruction for this step: read by the agent's next call on it, which is why it is
//   only offered while the step is still to finish;
// - planning it again from the phase the development is on: the Architect replaces the
//   phases still to build, keeping the ones built, and the new plan comes back to the
//   architecture gate.
//
// An answer that heard a request in the question says so (`change`), and offers the two
// ways to act on it. Nothing happens because the agent said it could: the person presses.
// What the agent wrote is read through `say()`; the instruction box it fills is editable
// and is sent as typed, so it is not.
import { useState } from "react";
import { describeError, type JobMessage, type StepTalk } from "../api/client";
import { isOwner } from "../api/gates";
import { useAsk, useMyTeam, useRedirect, useSteer, useTalk } from "../api/hooks";
import { useT } from "../i18n";
import { useSay } from "../i18n/said";
import { ROLE_LABEL } from "./agents";
import { timeAgo } from "./ui";

export function AgentTalk({
  jobId,
  stepKey,
  talk,
}: {
  jobId: string;
  stepKey: string;
  talk: StepTalk;
}) {
  const tx = useT();
  const team = useMyTeam();
  const said = useTalk(jobId, stepKey);
  const ask = useAsk(jobId, stepKey);
  const steer = useSteer(jobId, stepKey);
  const [text, setText] = useState("");
  const owner = isOwner(team.data);
  const agent = tx(ROLE_LABEL[talk.agent] ?? talk.agent);
  // a member writes to the agent they hold, and to no other
  const mayAsk = owner || (team.data?.agents ?? []).includes(talk.agent);
  const messages = said.data ?? [];
  const replies = (id: string) => messages.filter((m) => m.reply_to === id);
  const loose = messages.filter((m) => !m.reply_to);
  const send = (how: "ask" | "steer") => {
    const typed = text.trim();
    if (!typed) return;
    const done = { onSuccess: () => setText("") };
    if (how === "ask") ask.mutate(typed, done);
    else steer.mutate({ text: typed }, done);
  };
  const error = ask.error ?? steer.error;
  return (
    <section className="step-group agent-talk">
      <div className="step-group-head">
        <h4>{tx("Write to the agent")}</h4>
        <span className="faint tiny">{messages.length || ""}</span>
      </div>
      <div className="muted small">
        {tx(
          "Ask {agent} about this step and read its answer. When you want it done differently, tell it, or have the plan made again from here.",
          { agent },
        )}
      </div>
      {loose.length > 0 && (
        <ul className="talk-thread">
          {loose.map((m) => (
            <Said
              key={m.id}
              message={m}
              replies={replies(m.id)}
              jobId={jobId}
              stepKey={stepKey}
              talk={talk}
              owner={owner}
            />
          ))}
        </ul>
      )}
      {mayAsk ? (
        <form
          className="talk-form"
          onSubmit={(e) => {
            e.preventDefault();
            send("ask");
          }}
        >
          <textarea
            rows={2}
            value={text}
            placeholder={tx("e.g. why is the Bluetooth module written by hand?")}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                send("ask");
              }
            }}
          />
          <div className="row">
            <button className="btn primary small" disabled={!text.trim() || ask.isPending}>
              {ask.isPending ? tx("Sending…") : tx("Ask")}
            </button>
            {owner && talk.steer && (
              <button
                type="button"
                className="btn small"
                disabled={!text.trim() || steer.isPending}
                onClick={() => send("steer")}
                title={tx("read by {agent}'s next call on this step", { agent })}
              >
                {tx("Send as an instruction")}
              </button>
            )}
            {error && <span className="error small">{describeError(error)}</span>}
          </div>
        </form>
      ) : (
        <div className="faint small">{tx("This step's agent is somebody else's on the team.")}</div>
      )}
    </section>
  );
}

/** One thing the person said, and everything that came of it. */
function Said({
  message,
  replies,
  jobId,
  stepKey,
  talk,
  owner,
}: {
  message: JobMessage;
  replies: JobMessage[];
  jobId: string;
  stepKey: string;
  talk: StepTalk;
  owner: boolean;
}) {
  const tx = useT();
  const say = useSay();
  if (message.kind !== "question") return <Followed message={message} />;
  return (
    <li className="talk-turn">
      <div className="talk-bubble mine">
        <div className="talk-who">
          {message.by ?? tx("you")} · {timeAgo(message.at)}
        </div>
        <div className="talk-text">{message.text}</div>
      </div>
      {message.status === "answering" && (
        <div className="talk-bubble agent waiting">
          <span className="pulse-dot" /> {tx("Thinking…")}
        </div>
      )}
      {message.status === "failed" && (
        <div className="talk-bubble agent failed">
          {tx("No answer: {why}", { why: message.error ?? "" })}
        </div>
      )}
      {message.status === "answered" && (
        <div className="talk-bubble agent">
          <div className="talk-who">{tx(ROLE_LABEL[message.role ?? ""] ?? message.role ?? "")}</div>
          <div className="talk-text">{say(message.answer)}</div>
        </div>
      )}
      {message.change && owner && replies.length === 0 && (
        <Change question={message} jobId={jobId} stepKey={stepKey} talk={talk} />
      )}
      {replies.map((r) => (
        <Followed key={r.id} message={r} />
      ))}
    </li>
  );
}

/** An instruction or a re-plan, and whether it was acted on. */
function Followed({ message }: { message: JobMessage }) {
  const tx = useT();
  const head = message.kind === "replan" ? tx("Plan to be made again") : tx("Instruction");
  let state: string;
  if (message.kind === "steer") {
    state = message.consumed_at
      ? tx("read by {agent} {ago}", {
          agent: tx(ROLE_LABEL[message.consumed_by ?? ""] ?? message.consumed_by ?? ""),
          ago: timeAgo(message.consumed_at),
        })
      : tx("waiting for the agent's next call");
  } else {
    state =
      message.status === "applied"
        ? tx("sent to the Architect")
        : message.status === "dropped"
          ? tx("not acted on: the development was stopped or moved on")
          : tx("after the call it is on");
  }
  return (
    <li className={`talk-followed ${message.kind}`}>
      <div className="talk-who">
        {head} · {state}
      </div>
      <div className="talk-text">{message.text}</div>
    </li>
  );
}

/** What the agent understood the person to want changed, in a box they may edit, and the
 * two ways to act on it. */
function Change({
  question,
  jobId,
  stepKey,
  talk,
}: {
  question: JobMessage;
  jobId: string;
  stepKey: string;
  talk: StepTalk;
}) {
  const tx = useT();
  const [text, setText] = useState(question.change ?? "");
  const steer = useSteer(jobId, stepKey);
  const redirect = useRedirect(jobId);
  if (!talk.steer && !talk.replan) return null;
  const typed = text.trim();
  const error = steer.error ?? redirect.error;
  return (
    <div className="talk-change">
      <div className="talk-who">{tx("The agent heard a change")}</div>
      <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row">
        {talk.steer && (
          <button
            className="btn small"
            disabled={!typed || steer.isPending}
            onClick={() => steer.mutate({ text: typed, replyTo: question.id })}
            title={tx("the agent reads it on its next call on this step")}
          >
            {tx("Do it in this step")}
          </button>
        )}
        {talk.replan && (
          <button
            className="btn small"
            disabled={!typed || redirect.isPending}
            onClick={() => redirect.mutate({ text: typed, replyTo: question.id })}
            title={tx(
              "the Architect plans the phases still to build again; what is built stays, and you approve the new plan",
            )}
          >
            {tx("Plan it again from here")}
          </button>
        )}
        {error && <span className="error small">{describeError(error)}</span>}
      </div>
    </div>
  );
}
