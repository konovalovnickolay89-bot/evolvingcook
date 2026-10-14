import type { ReactNode } from "react";
import { toChatBlocks } from "@/lib/chatFormat";

/** "Mise:", "Lead:", "HACCP:", "Step 2:" — a short label leading a line. */
const LEAD_LABEL = /^([A-Z][A-Za-z0-9/&()'’ -]{0,22}):\s+/;
const SAFETY_LABEL = /^(haccp|allergens?|food safety|safety|warning)$/i;
const EMPHASIS = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g;

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text;
  const lead = LEAD_LABEL.exec(rest);
  if (lead) {
    const name = lead[1] ?? "";
    out.push(
      <span
        key="label"
        className={
          SAFETY_LABEL.test(name.trim())
            ? "chat-md__label chat-md__label--safety"
            : "chat-md__label"
        }
      >
        {name}:
      </span>,
      " ",
    );
    rest = rest.slice(lead[0].length);
  }
  rest.split(EMPHASIS).forEach((part, i) => {
    if (!part) return;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      out.push(<strong key={i}>{part.slice(2, -2)}</strong>);
    } else if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      out.push(<em key={i}>{part.slice(1, -1)}</em>);
    } else {
      out.push(part);
    }
  });
  return out;
}

/** Companion reply: headings, bullets, steps and bold labels — no HTML
 *  injection, every piece is a React text node. */
export function ChatText({ text }: { text: string }) {
  return (
    <div className="chat-md">
      {toChatBlocks(text).map((b, i) => {
        if (b.kind === "heading")
          return (
            <p key={i} className="chat-md__h">
              {b.text}
            </p>
          );
        if (b.kind === "bullets")
          return (
            <ul key={i}>
              {b.items.map((it, j) => (
                <li key={j}>{inline(it)}</li>
              ))}
            </ul>
          );
        if (b.kind === "steps")
          return (
            <ol key={i} start={b.start}>
              {b.items.map((it, j) => (
                <li key={j}>{inline(it)}</li>
              ))}
            </ol>
          );
        return (
          <p key={i}>
            {b.lines.map((ln, j) => (
              <span key={j}>
                {j > 0 ? <br /> : null}
                {inline(ln)}
              </span>
            ))}
          </p>
        );
      })}
    </div>
  );
}
