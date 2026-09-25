// Where somebody writes to us. The form is short on purpose — a category, a line and the
// thing that went wrong — and underneath it sits what this account has asked before, so
// nobody has to wonder whether their question got through.
import { useState, type FormEvent } from "react";
import { describeError, type SupportCategory, type SupportRequest } from "../api/client";
import { useMySupportRequests, useSendSupportRequest } from "../api/hooks";
import { useAuth } from "../auth/AuthProvider";
import { IconCheck, IconLifebuoy } from "../components/icons";
import { Empty, ErrorBox, Loading, PageHead, formatTime } from "../components/ui";
import { useLang, useT } from "../i18n";

const CATEGORIES: { value: SupportCategory; label: string }[] = [
  { value: "question", label: "A question" },
  { value: "problem", label: "Something is broken" },
  { value: "billing", label: "Billing" },
  { value: "feature", label: "A request" },
  { value: "other", label: "Something else" },
];

export function SupportPage() {
  const tx = useT();
  const { lang } = useLang();
  const { user } = useAuth();
  const send = useSendSupportRequest();
  const mine = useMySupportRequests();

  const [category, setCategory] = useState<SupportCategory>("question");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<SupportRequest | null>(null);

  const replyTo = email.trim() || user?.email || "";

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSent(null);
    send.mutate(
      {
        category,
        subject: subject.trim(),
        message: message.trim(),
        email: email.trim() || null,
        lang,
      },
      {
        onSuccess: (created) => {
          setSent(created);
          setSubject("");
          setMessage("");
        },
      },
    );
  };

  return (
    <div>
      <PageHead title={tx("Support")} subtitle={tx("Write to us and we answer by email.")} />
      <p className="muted">
        {tx(
          "Tell us what you need. It reaches us as an email, and we reply to the address below — so a question written here does not need chasing anywhere else.",
        )}
      </p>

      {sent && <SentNotice request={sent} />}

      <form className="card stack" onSubmit={submit}>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="support-category">{tx("What is it about?")}</label>
            <select
              id="support-category"
              value={category}
              onChange={(e) => setCategory(e.target.value as SupportCategory)}
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {tx(c.label)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="support-email">{tx("Reply to")}</label>
            <input
              id="support-email"
              type="email"
              autoComplete="email"
              value={email}
              placeholder={user?.email ?? tx("your address")}
              onChange={(e) => setEmail(e.target.value)}
            />
            <div className="muted small">
              {user?.email
                ? tx("Empty means {email}, the address on your account.", { email: user.email })
                : tx("Your account has no address, so please give one here.")}
            </div>
          </div>
        </div>
        <div className="field">
          <label htmlFor="support-subject">{tx("Subject")}</label>
          <input
            id="support-subject"
            type="text"
            maxLength={200}
            required
            value={subject}
            placeholder={tx("One line: what happened")}
            onChange={(e) => setSubject(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="support-message">{tx("Your message")}</label>
          <textarea
            id="support-message"
            rows={8}
            maxLength={10000}
            required
            value={message}
            placeholder={tx(
              "What you were doing, what you expected, and what happened instead. A project name or a job link helps.",
            )}
            onChange={(e) => setMessage(e.target.value)}
          />
          <div className="muted small">{message.length}/10000</div>
        </div>
        {send.error && <div className="callout error">{describeError(send.error)}</div>}
        <div className="row">
          <button
            className="btn primary"
            disabled={send.isPending || !subject.trim() || !message.trim() || !replyTo}
          >
            <IconLifebuoy /> {send.isPending ? tx("Sending…") : tx("Send")}
          </button>
        </div>
      </form>

      <h3 style={{ marginTop: 28 }}>{tx("What you have asked before")}</h3>
      {mine.isLoading ? (
        <Loading rows={2} />
      ) : mine.error ? (
        <ErrorBox error={mine.error} />
      ) : mine.data!.length === 0 ? (
        <Empty title={tx("Nothing yet.")} icon={<IconLifebuoy />}>
          {tx("Anything you send will be listed here with its state.")}
        </Empty>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>{tx("Subject")}</th>
                <th>{tx("About")}</th>
                <th>{tx("Sent")}</th>
                <th>{tx("State")}</th>
              </tr>
            </thead>
            <tbody>
              {mine.data!.map((r) => (
                <tr key={r.id}>
                  <td className="truncate">{r.subject}</td>
                  <td className="muted">{tx(labelOf(r.category))}</td>
                  <td className="muted">{formatTime(r.created_at)}</td>
                  <td>
                    {r.status === "closed" ? (
                      <span className="badge ok plain">
                        <IconCheck /> {tx("answered")}
                      </span>
                    ) : (
                      <span className="badge idle">{tx("open")}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** What happened to the letter. `failed` is worth saying plainly: the request is kept
 *  either way, but somebody should know it has not left the building yet. */
function SentNotice({ request }: { request: SupportRequest }) {
  const tx = useT();
  if (request.delivery === "sent") {
    return (
      <div className="callout notice">
        {tx("Sent. We reply to {email}.", { email: request.email })}
      </div>
    );
  }
  if (request.delivery === "outbox") {
    return (
      <div className="callout notice">
        {tx(
          "Saved. This installation has no mail server configured yet, so an administrator reads it in the app rather than by email.",
        )}
      </div>
    );
  }
  return (
    <div className="callout warn">
      {tx(
        "Saved, but the email could not be sent — an administrator can still read it here. Nothing you wrote was lost.",
      )}
    </div>
  );
}

function labelOf(value: string): string {
  return CATEGORIES.find((c) => c.value === value)?.label ?? "Something else";
}
