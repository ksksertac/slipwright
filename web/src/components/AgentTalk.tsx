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
// It reads like a chat: the conversation scrolls in a box of its own, newest at the
// bottom and followed as answers arrive, and there is one place to write. An answer that
// heard a request in the question (`change`) puts what it heard into that box, where the
// person edits it and presses one of the two ways to act on it -- a second box under the
// answer for the same words read as two places to write. Nothing happens because the agent
// said it could: the person presses. What the agent wrote is read through `say()`; the
// box holds its words as written, since what is sent goes on as typed.
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { describeError, type JobMessage, type StepTalk } from "../api/client";
import { isOwner } from "../api/gates";
import { keys, useAsk, useMyTeam, useRedirect, useSteer, useTalk } from "../api/hooks";
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
  const qc = useQueryClient();
  const team = useMyTeam();
  const said = useTalk(jobId, stepKey);
  const ask = useAsk(jobId, stepKey);
  const steer = useSteer(jobId, stepKey);
  const redirect = useRedirect(jobId);
  const [text, setText] = useState("");
  // the question whose heard change is in the box, so what is sent answers it
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const offered = useRef<Set<string>>(new Set());
  const scroller = useRef<HTMLDivElement>(null);
  const owner = isOwner(team.data);
  const agent = tx(ROLE_LABEL[talk.agent] ?? talk.agent);
  // a member writes to the agent they hold, and to no other
  const mayAsk = owner || (team.data?.agents ?? []).includes(talk.agent);
  const messages = said.data ?? [];
  const replies = (id: string) => messages.filter((m) => m.reply_to === id);
  const loose = messages.filter((m) => !m.reply_to);

  // a change the agent heard, not yet acted on, goes into the box -- once, and never over
  // something the person is already writing
  const heard = owner
    ? [...loose]
        .reverse()
        .find((m) => m.kind === "question" && m.change && replies(m.id).length === 0)
    : undefined;
  useEffect(() => {
    if (!heard?.change || offered.current.has(heard.id)) return;
    offered.current.add(heard.id);
    if (text.trim()) return;
    setText(heard.change);
    setReplyTo(heard.id);
  }, [heard?.id, heard?.change, text]);

  // follow the conversation as it grows: newest at the bottom, like a chat
  const last = messages[messages.length - 1];
  const tail = `${messages.length}:${last?.status ?? ""}:${last?.id ?? ""}`;
  useEffect(() => {
    const box = scroller.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [tail]);

  const clear = () => {
    setText("");
    setReplyTo(null);
  };
  const typed = text.trim();
  const fromHeard = replyTo !== null;
  const send = (how: "ask" | "steer" | "replan") => {
    if (!typed) return;
    if (how === "ask") ask.mutate(typed, { onSuccess: clear });
    else if (how === "steer") steer.mutate({ text: typed, replyTo }, { onSuccess: clear });
    else
      redirect.mutate(
        { text: typed, replyTo },
        {
          onSuccess: () => {
            clear();
            void qc.invalidateQueries({ queryKey: keys.talk(jobId, stepKey) });
          },
        },
      );
  };
  const error = ask.error ?? steer.error ?? redirect.error;
  const busy = ask.isPending || steer.isPending || redirect.isPending;
  return (
    <section className="step-group agent-talk">
      <div className="step-group-head">
        <h4>{tx("Write to the agent")}</h4>
        <span className="faint tiny">{messages.length || ""}</span>
      </div>
      <div className="talk-window">
        <div className="talk-scroll" ref={scroller}>
          {loose.length === 0 ? (
            <div className="muted small talk-empty">
              {tx(
                "Ask {agent} about this step and read its answer. When you want it done differently, tell it, or have the plan made again from here.",
                { agent },
              )}
            </div>
          ) : (
            <ul className="talk-thread">
              {loose.map((m) => (
                <Said key={m.id} message={m} replies={replies(m.id)} heard={m.id === replyTo} />
              ))}
            </ul>
          )}
        </div>
        {mayAsk ? (
          <form
            className="talk-form"
            onSubmit={(e) => {
              e.preventDefault();
              send(fromHeard ? "steer" : "ask");
            }}
          >
            {fromHeard && (
              <div className="talk-heard">
                <span>
                  {tx("The agent heard a change: edit it, then choose what to do with it")}
                </span>
                <button type="button" className="btn ghost tiny" onClick={clear}>
                  {tx("Clear")}
                </button>
              </div>
            )}
            <textarea
              rows={fromHeard ? 3 : 2}
              value={text}
              placeholder={tx("e.g. why is the Bluetooth module written by hand?")}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  send(fromHeard ? "steer" : "ask");
                }
              }}
              aria-label={tx("Write to the agent")}
            />
            <div className="row">
              {!fromHeard && (
                <button type="submit" className="btn primary small" disabled={!typed || busy}>
                  {ask.isPending ? tx("Sending…") : tx("Ask")}
                </button>
              )}
              {owner && talk.steer && (
                <button
                  type="button"
                  className={`btn small ${fromHeard ? "primary" : ""}`}
                  disabled={!typed || busy}
                  onClick={() => send("steer")}
                  title={tx("read by {agent}'s next call on this step", { agent })}
                >
                  {fromHeard ? tx("Do it in this step") : tx("Send as an instruction")}
                </button>
              )}
              {owner && talk.replan && (fromHeard || typed) && (
                <button
                  type="button"
                  className="btn small"
                  disabled={!typed || busy}
                  onClick={() => send("replan")}
                  title={tx(
                    "the Architect plans the phases still to build again; what is built stays, and you approve the new plan",
                  )}
                >
                  {tx("Plan it again from here")}
                </button>
              )}
              {fromHeard && (
                <button
                  type="button"
                  className="btn ghost small"
                  disabled={!typed || busy}
                  onClick={() => send("ask")}
                  title={tx("ask it instead: nothing is changed")}
                >
                  {tx("Ask")}
                </button>
              )}
              {error && <span className="error small">{describeError(error)}</span>}
            </div>
          </form>
        ) : (
          <div className="faint small">
            {tx("This step's agent is somebody else's on the team.")}
          </div>
        )}
      </div>
    </section>
  );
}

/** One thing the person said, and everything that came of it. */
function Said({
  message,
  replies,
  heard,
}: {
  message: JobMessage;
  replies: JobMessage[];
  heard: boolean;
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
          {message.change && replies.length === 0 && (
            <div className="talk-who talk-change-note">
              {heard
                ? tx("It heard a change -- it is in the box below")
                : tx("It heard a change: {change}", { change: message.change })}
            </div>
          )}
        </div>
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
    const replan: Record<string, string> = {
      applied: "sent to the Architect",
      dropped: "not acted on: the development was stopped or moved on",
    };
    state = tx(replan[message.status] ?? "after the call it is on");
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
