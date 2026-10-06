import { useEffect, useRef, useState } from "react";
import {
  getCompanionProfile,
  postCompanionChat,
  putCompanionProfile,
  type ChatMessage,
} from "@/api/companion";
import { ApiError } from "@/api/client";
import { todayServiceDate } from "@/lib/dates";
import { useDictation } from "@/lib/useDictation";

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

  /* Companion tuner — the house profile carried into every prompt. */
  const [tuneOpen, setTuneOpen] = useState(false);
  const [profileDraft, setProfileDraft] = useState<string | null>(null);
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileMsg, setProfileMsg] = useState<string | null>(null);

  const dictation = useDictation((text) =>
    setDraft((d) => (d ? `${d} ${text}` : text)),
  );

  async function openTune() {
    setTuneOpen(true);
    setProfileMsg(null);
    if (profileDraft !== null) return;
    setProfileBusy(true);
    try {
      const p = await getCompanionProfile();
      setProfileDraft(p.text);
    } catch {
      setProfileDraft("");
      setProfileMsg(
        "Couldn't load the saved profile — saving will overwrite it.",
      );
    } finally {
      setProfileBusy(false);
    }
  }

  async function saveProfile() {
    if (profileDraft === null) return;
    setProfileBusy(true);
    setProfileMsg(null);
    try {
      const p = await putCompanionProfile(profileDraft);
      setProfileDraft(p.text);
      setProfileMsg("Saved — the companion now carries your rules.");
    } catch (e) {
      setProfileMsg(
        e instanceof ApiError && (e.status === 404 || e.status === 405)
          ? "Tuner isn't on the kitchen server yet — it arrives with the next backend update."
          : e instanceof Error
            ? e.message
            : "Save failed",
      );
    } finally {
      setProfileBusy(false);
    }
  }

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
        <span className="chat-header-actions">
          <button
            type="button"
            className="link-back"
            onClick={() => (tuneOpen ? setTuneOpen(false) : void openTune())}
          >
            {tuneOpen ? "Close tuner" : "Tune"}
          </button>
          {messages.length > 0 ? (
            <button type="button" className="link-back" onClick={clearChat}>
              Clear
            </button>
          ) : null}
        </span>
      </div>
      <div>
        <h2 className="page-title">Companion</h2>
        <p className="page-lead" style={{ marginBottom: 0 }}>
          Knows today's boards, log and 86s. Advice only — check against house
          SOPs.
        </p>
      </div>

      {tuneOpen ? (
        <div className="tune-card">
          <h3 className="brief-card__title">Your standing rules</h3>
          <p className="board-row__meta">
            Carried into every answer and daily brief. Suppliers' cutoffs, par
            habits, dishes you run, allergy rules — your words.
          </p>
          <textarea
            className="field__input note-edit__area"
            rows={5}
            maxLength={4000}
            value={profileDraft ?? ""}
            disabled={profileBusy || profileDraft === null}
            onChange={(e) => setProfileDraft(e.target.value)}
            placeholder={
              profileBusy && profileDraft === null
                ? "Loading…"
                : "e.g. Veg order cuts off 15:00 Mon–Fri. Skybar runs small plates only. Always flag sesame."
            }
          />
          <button
            type="button"
            className="btn btn--primary btn--block"
            disabled={profileBusy || profileDraft === null}
            onClick={() => void saveProfile()}
          >
            {profileBusy ? "Saving…" : "Save rules"}
          </button>
          {profileMsg ? <p className="board-row__meta">{profileMsg}</p> : null}
        </div>
      ) : null}

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
          placeholder={
            dictation.listening ? "Listening…" : "Ask the companion…"
          }
          enterKeyHint="send"
          autoComplete="off"
        />
        {dictation.supported ? (
          <button
            type="button"
            className={`btn btn--ghost voice-btn${dictation.listening ? " is-listening" : ""}`}
            aria-pressed={dictation.listening}
            aria-label={
              dictation.listening ? "Stop dictating" : "Dictate a message"
            }
            onClick={() =>
              dictation.listening ? dictation.stop() : dictation.start()
            }
          >
            {dictation.listening ? "◼" : "⏺"}
          </button>
        ) : null}
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
