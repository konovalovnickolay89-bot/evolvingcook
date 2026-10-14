/**
 * Companion reply text — repair + structure (D16).
 *
 * Mirrors backend assist/companion.py `_as_text` / `_repair_reply`: older
 * servers str()'d nested JSON-mode answers, so stored replies can read
 * "{'actions': [...], 'tip': '...'}". We turn those back into text, then
 * split text into blocks the chat renders (headings, bullets, paragraphs).
 */

/** Minimal Python-literal reader (str/number/bool/None/list/tuple/dict) —
 *  enough to undo an old str(dict) reply. Throws on anything else. */
export function parsePyLiteral(src: string): unknown {
  let i = 0;
  const fail = (): never => {
    throw new SyntaxError(`not a Python literal (at ${i})`);
  };
  const ws = () => {
    while (i < src.length && /\s/.test(src.charAt(i))) i++;
  };

  function str(): string {
    const quote = src[i++];
    let out = "";
    while (i < src.length) {
      const c = src[i++];
      if (c === quote) return out;
      if (c !== "\\") {
        out += c;
        continue;
      }
      const e = src[i++];
      if (e === "n") out += "\n";
      else if (e === "t") out += "\t";
      else if (e === "r") out += "\r";
      else if (e === "x" || e === "u" || e === "U") {
        const n = e === "x" ? 2 : e === "u" ? 4 : 8;
        const code = parseInt(src.slice(i, i + n), 16);
        if (Number.isNaN(code)) fail();
        out += String.fromCodePoint(code);
        i += n;
      } else out += e ?? "";
    }
    return fail();
  }

  function items(close: string, pair: boolean): [unknown, unknown][] {
    i++; // opening bracket
    const out: [unknown, unknown][] = [];
    ws();
    if (src[i] === close) {
      i++;
      return out;
    }
    for (;;) {
      const first = value();
      ws();
      let second: unknown = undefined;
      if (pair) {
        if (src[i] !== ":") fail();
        i++;
        second = value();
        ws();
      }
      out.push([first, second]);
      if (src[i] === ",") {
        i++;
        ws();
        if (src[i] !== close) continue;
      }
      if (src[i] === close) {
        i++;
        return out;
      }
      fail();
    }
  }

  function value(): unknown {
    ws();
    const c = src[i];
    if (c === "{")
      return Object.fromEntries(
        items("}", true).map(([k, v]) => [String(k), v]),
      );
    if (c === "[") return items("]", false).map(([v]) => v);
    if (c === "(") return items(")", false).map(([v]) => v);
    if (c === "'" || c === '"') return str();
    const m = /^(?:True|False|None|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(
      src.slice(i),
    );
    if (!m) return fail();
    i += m[0].length;
    if (m[0] === "True") return true;
    if (m[0] === "False") return false;
    if (m[0] === "None") return null;
    return Number(m[0]);
  }

  const v = value();
  ws();
  if (i !== src.length) fail();
  return v;
}

const UNWRAP_KEYS = new Set(["reply", "answer", "text", "message", "content"]);

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj =>
  !!v && typeof v === "object" && !Array.isArray(v);
const isContainer = (v: unknown) => Array.isArray(v) || isObj(v);

function label(key: string): string {
  const s = key.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1); // keep "HACCP"
}

/** Structured model output → chat text (same rules as the backend). */
export function structuredToText(value: unknown, depth = 0): string {
  if (value == null) return "";
  if (typeof value === "string") return value.trim();
  if (!isContainer(value)) return String(value);
  if (depth > 4) return JSON.stringify(value);
  if (Array.isArray(value)) {
    const lines: string[] = [];
    for (const item of value) {
      if (isObj(item) && !Object.values(item).some(isContainer)) {
        const flat = Object.entries(item)
          .filter(([, v]) => structuredToText(v))
          .map(([k, v]) => `${label(k)}: ${structuredToText(v)}`)
          .join(" · ");
        if (flat) lines.push(`- ${flat}`);
        continue;
      }
      const text = structuredToText(item, depth + 1);
      if (text)
        lines.push(
          isContainer(item) ? text : `- ${text.replace(/\n/g, "\n  ")}`,
        );
    }
    return lines.join("\n");
  }
  const entries = Object.entries(value);
  const only = entries.length === 1 ? entries[0] : undefined;
  if (only && UNWRAP_KEYS.has(only[0].toLowerCase())) {
    return structuredToText(only[1], depth + 1);
  }
  const blocks: string[] = [];
  for (const [k, v] of entries) {
    const text = structuredToText(v, depth + 1);
    if (!text) continue;
    blocks.push(
      isContainer(v) ? `**${label(k)}**\n${text}` : `**${label(k)}:** ${text}`,
    );
  }
  return blocks.join("\n\n");
}

/** Old replies stored as a Python repr / JSON object → readable text. */
export function repairReply(content: string): string {
  const s = content.trim();
  if (!s || (s[0] !== "{" && s[0] !== "[")) return content;
  for (const parse of [JSON.parse, parsePyLiteral] as const) {
    try {
      const value: unknown = parse(s);
      if (isContainer(value)) return structuredToText(value) || content;
    } catch {
      /* try the next reader; keep the original if none fit */
    }
  }
  return content;
}

export type ChatBlock =
  | { kind: "heading"; text: string }
  | { kind: "para"; lines: string[] }
  | { kind: "bullets"; items: string[] }
  | { kind: "steps"; items: string[]; start: number };

const BULLET = /^\s*[-•*]\s+(.*)$/;
const STEP = /^\s*(\d{1,2})[.)]\s+(.*)$/;
const MD_HEADING = /^\s*#{1,4}\s+(.*)$/;
const BOLD_LINE = /^\s*\*\*([^*]+?)\*\*:?\s*$/;

/** Reply text → blocks: '**Heading**' / '# Heading' lines, '- ' bullets,
 *  '1.' steps, paragraphs (single newlines kept as line breaks). */
export function toChatBlocks(text: string): ChatBlock[] {
  const blocks: ChatBlock[] = [];
  const last = () => blocks[blocks.length - 1];
  for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
    if (!raw.trim()) {
      blocks.push({ kind: "para", lines: [] }); // paragraph break marker
      continue;
    }
    const heading = MD_HEADING.exec(raw) ?? BOLD_LINE.exec(raw);
    const bullet = BULLET.exec(raw);
    const step = STEP.exec(raw);
    const prev = last();
    if (heading) {
      blocks.push({ kind: "heading", text: (heading[1] ?? "").trim() });
    } else if (bullet) {
      const item = (bullet[1] ?? "").trim();
      if (prev?.kind === "bullets") prev.items.push(item);
      else blocks.push({ kind: "bullets", items: [item] });
    } else if (step) {
      const item = (step[2] ?? "").trim();
      if (prev?.kind === "steps") prev.items.push(item);
      else blocks.push({ kind: "steps", items: [item], start: Number(step[1]) });
    } else if (
      /^\s{2,}\S/.test(raw) &&
      (prev?.kind === "bullets" || prev?.kind === "steps")
    ) {
      const n = prev.items.length - 1; // wrapped item continues the last one
      prev.items[n] = `${prev.items[n] ?? ""} ${raw.trim()}`;
    } else if (prev?.kind === "para" && prev.lines.length > 0) {
      prev.lines.push(raw.trim());
    } else {
      blocks.push({ kind: "para", lines: [raw.trim()] });
    }
  }
  return blocks.filter((b) => b.kind !== "para" || b.lines.length > 0);
}
