# Evolving Cook FE fixes — FE-1 … FE-7 + presentation

**This session does not have the live Grok Build workspace.**  
Copy these files into the Build project (`/workspace/src/…`), then rebuild.

## Files

| Path in package | Destination |
| --- | --- |
| `src/components/ProposalCard.tsx` | replace |
| `src/pages/InboxPage.tsx` | replace |
| `src/lib/proposalTarget.ts` | replace |
| `src/contract.ts` | merge reject labels + keep rest of your contract.ts |
| `css-snippet.css` | append to `src/styles/app.css` |
| `src/components/BoardLine.note-assist.patch.md` | manual edit BoardLine (FE-4, FE-6) |

## Checklist

| ID | Fix |
| --- | --- |
| FE-1 | `targetConfidenceOf` reads `proposal.target_confidence`; maps `medium→med`; no rationale/model heuristic |
| FE-2 | Low-conf: no disabled Accept on collapsed card; expand + warning; accept only in body |
| FE-3 | `compact` default **true**; Inbox + BoardLine pass `compact`; parse_error auto-opens |
| FE-4 | **No** `createAssistJob` on ordinary note save; server auto-enqueue only |
| FE-5 | "Something else…" opens text input; submits as reason |
| FE-6 | Poll timer ref; clear on unmount and when `pendingInline` arrives |
| FE-7 | Trust `accept_able`; friction only via conf level |
| Pres | Titles from note; To review/Done; resolved names; target pill+banner; relative ages; parse_error Rewrite/Dismiss; no conf-chip; rationale before ` \| ` |

## Legitimate `/assist/jobs` use

Only **parse_error → Rewrite → Resend** (InboxPage `onRewrite`).  
Ordinary note Save = PATCH only.

## After apply (in Build)

```sh
npm run typecheck
npm run build
# restart preview / startup.sh
```
