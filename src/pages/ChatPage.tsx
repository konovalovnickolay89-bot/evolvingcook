import { useEffect, useRef, useState } from "react";
import {
  postCompanionChat,
  type ChatMessage,
} from "@/api/companion";
import { ApiError } from "@/api/client";
import { todayServiceDate } from "@/lib/dates";

const HISTORY_KEY = "evolvingcook.companionChat.v1";
const HISTORY_CAP = 40;

/** One-tap openers for a chef mid-shift. */
const STARTERS = [
  "What should I prioritise right now?",
  "Tips for tonight's service",
  "Recipe idea from today's leftovers",
  "Help me scale a recipe",
];

function readHistory(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr)) return [];
    return arr
      .filter(
        (m): m is ChatMessage =>
          !!m &&
          typeof m === "object" &&
          ((m as ChatMessage).role === "user" ||
            (m as ChatMessage).role === "assistant") &&
          typeof (m as ChatMessage).content === "string",
      )
      .slice(-HISTORY_CAP);
  } catch {
    return [];
  }
}

function writeHistory(msgs: ChatMessage[]): void {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(msgs.slice(-HISTORY_CAP)));
  } catch {
    /* ignore */
  }
}

type Props = { onBack: () => void };

export function ChatPage({ onBack }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>(() => readHistory());
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages, busy]);

  async function send(text: string) {
    const content = text.trim();
    if (!content || busy) return;
    const next: ChatMessage[] = [...messages, { role: "user", content }];
    setMessages(next);
    writeHistory(next);
    setDraft("");
    setError(null);
    setBusy(true);
    try {
      const out = await postCompanionChat(next.slice(-12), todayServiceDate());
      const withReply: ChatMessage[] = [
        ...next,
        { role: "assistant", content: out.reply },
      ];
      setMessages(withReply);
      writeHistory(withReply);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 405)) {
        // Old backend without D16 — not a Mistral problem.
        setError(
          "Companion isn't on the kitchen server yet — it arrives with the next backend update.",
        );
      } else if (e instanceof ApiError && e.status === 503) {
        setError(
          "Companion offline — it comes back when the kitchen brain is connected.",
        );
      } else {
        setError(e instanceof Error ? e.message : "Companion request failed");
      }
    } finally {
      setBusy(false);
    }
  }

  function clearChat() {
    setMessages([]);
    writeHistory([]);
    setError(null);
  }

  return (
    <div className="stack chat-page">
      <div className="day-home__title-row">
        <button type="button" className="link-back" onClick={onBack}>
          ← Back
        </button>
        {messages.length > 0 ? (
          <button type="button" className="link-back" onClick={clearChat}>
            Clear
          </button>
        ) : null}
      </div>
      <div>
        <h2 className="page-title">Companion</h2>
        <p className="page-lead" style={{ marginBottom: 0 }}>
          Knows today's boards, log and 86s. Advice only — check against house
          SOPs.
        </p>
      </div>

      {messages.length === 0 ? (
        <div className="chat-starters">
          {STARTERS.map((s) => (
            <button
              key={s}
              type="button"
              className="chip chat-starter"
              disabled={busy}
              onClick={() => void send(s)}
            >
              {s}
            </button>
          ))}
        </div>
      ) : null}

      <div className="chat-thread" aria-live="polite">
        {messages.map((m, i) => (
          <div
            key={`${i}-${m.role}`}
            className={`chat-msg chat-msg--${m.role === "user" ? "user" : "assist"}`}
          >
            {m.role === "assistant" ? (
              <span className="order-assist__badge chat-msg__badge" aria-hidden>
                A
              </span>
            ) : null}
            <div className="chat-msg__body">{m.content}</div>
          </div>
        ))}
        {busy ? (
          <div className="chat-msg chat-msg--assist">
            <span className="order-assist__badge chat-msg__badge" aria-hidden>
              A
            </span>
            <div className="chat-msg__body chat-msg__body--thinking">
              thinking…
            </div>
          </div>
        ) : null}
        <div ref={endRef} />
      </div>

      {error ? <p className="field__error">{error}</p> : null}

      <form
        className="chat-compose"
        onSubmit={(e) => {
          e.preventDefault();
          void send(draft);
        }}
      >
        <input
          className="field__input"
          value={draft}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask the companion…"
          enterKeyHint="send"
          autoComplete="off"
        />
        <button
          type="submit"
          className="btn btn--primary"
          disabled={busy || !draft.trim()}
        >
          Send
        </button>
      </form>
    </div>
  );
}
