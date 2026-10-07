# BoardLine — FE-4 + FE-6 (apply in Build workspace)

## FE-4 · Do not file parse_note jobs on ordinary note save

In `saveNoteOnly()`:

1. **Delete** `createAssistJob` call and any `parseNoteContext` import.
2. Flow is only: `await onSaveNotes(line, noteDraft)` → set chip `parsing` if text non-empty → poll board.
3. Server auto-enqueues via `maybe_auto_enqueue_parse_note_for_line` on PATCH.
4. `/assist/jobs` has **no dedupe** — client jobs create a second A2A task.

## FE-6 · Cancel poll on unmount / pending arrival

```tsx
// state
const pollTimerRef = useRef<number | null>(null);

function clearPoll() {
  if (pollTimerRef.current != null) {
    window.clearTimeout(pollTimerRef.current);
    pollTimerRef.current = null;
  }
}

useEffect(() => {
  if (pendingInline) {
    setAssistState("ready");
    clearPoll();
  } else {
    setAssistState((prev) => (prev === "ready" ? "idle" : prev));
  }
}, [pendingInline]);

useEffect(() => () => clearPoll(), []);

async function saveNoteOnly() {
  if (!onSaveNotes) return;
  setSaveMsg(null);
  const text = noteDraft.trim();
  await onSaveNotes(line, noteDraft);
  if (!text) {
    setAssistState("idle");
    clearPoll();
    return;
  }
  setAssistState("parsing");
  clearPoll();
  const started = Date.now();
  const tick = () => {
    void qc.invalidateQueries({ queryKey: ["board"] });
    if (Date.now() - started > 25_000) {
      setAssistState((s) => (s === "parsing" ? "idle" : s));
      pollTimerRef.current = null;
      return;
    }
    pollTimerRef.current = window.setTimeout(tick, 2000);
  };
  pollTimerRef.current = window.setTimeout(tick, 1200);
}
```

## Inline ProposalCard

```tsx
<ProposalCard
  proposal={pendingInline}
  compact
  busy={actionBusy}
  onAccept={onAccept}
  onReject={onReject}
/>
```
