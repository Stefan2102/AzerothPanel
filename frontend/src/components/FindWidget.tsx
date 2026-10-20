import { useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import type { EditorState } from "@codemirror/state";
import { EditorView, type Panel, type ViewUpdate } from "@codemirror/view";
import {
  closeSearchPanel, findNext, findPrevious, getSearchQuery, replaceAll, replaceNext, search, SearchQuery, setSearchQuery,
} from "@codemirror/search";
import { ArrowDown, ArrowUp, CaseSensitive, ChevronRight, Regex, Replace, ReplaceAll, WholeWord, X } from "lucide-react";
import { cx } from "./ui";

const MAX_COUNT = 9999;

/** "3 of 12": all matches and which one the selection is on (0 = none). */
function matches(state: EditorState, q: SearchQuery): { total: number; current: number } {
  if (!q.valid || !q.search) return { total: 0, current: 0 };
  const sel = state.selection.main;
  const cursor = q.getCursor(state);
  let total = 0;
  let current = 0;
  for (let r = cursor.next(); !r.done && total < MAX_COUNT; r = cursor.next()) {
    total++;
    if (r.value.from === sel.from && r.value.to === sel.to) current = total;
  }
  return { total, current };
}

function IconButton({ title, active, disabled, onClick, children }: { title: string; active?: boolean; disabled?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      aria-pressed={active}
      disabled={disabled}
      onMouseDown={(e) => e.preventDefault()}      // keep the focus in the field
      onClick={onClick}
      className={cx(
        "grid size-6 shrink-0 place-items-center rounded transition-colors disabled:opacity-35",
        active ? "bg-accent-soft text-accent-text ring-1 ring-accent/60" : "text-muted hover:bg-card-2 hover:text-text",
      )}
    >
      {children}
    </button>
  );
}

/** VS Code-style find / replace box in the panel's colours. Reads its query from the editor state. */
function Find({ view }: { view: EditorView }) {
  const [replacing, setReplacing] = useState(false);
  // Where the cursor was when the box opened: typing jumps to the first match from there (like VS Code).
  const [anchor] = useState(() => view.state.selection.main.from);
  const q = getSearchQuery(view.state);
  const { total, current } = matches(view.state, q);
  const set = (spec: Partial<{ search: string; replace: string; caseSensitive: boolean; wholeWord: boolean; regexp: boolean }>) => {
    const next = new SearchQuery({
      search: q.search, replace: q.replace, caseSensitive: q.caseSensitive, wholeWord: q.wholeWord, regexp: q.regexp, ...spec,
    });
    view.dispatch({ effects: setSearchQuery.of(next) });
    if ("replace" in spec || !next.valid || !next.search) return;
    const cursor = next.getCursor(view.state, anchor);
    let hit = cursor.next();
    if (hit.done) hit = next.getCursor(view.state).next();        // wrap around to the top
    if (!hit.done) view.dispatch({ selection: { anchor: hit.value.from, head: hit.value.to }, scrollIntoView: true });
  };
  const close = () => { closeSearchPanel(view); view.focus(); };
  const keys = (e: React.KeyboardEvent, enter: () => void) => {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "Enter") { e.preventDefault(); if (e.shiftKey) findPrevious(view); else enter(); }
  };
  const invalid = !!q.search && !q.valid;
  const field = "h-7 min-w-0 flex-1 bg-transparent px-2 text-[13px] text-text outline-none placeholder:text-faint";

  return (
    <div className="flex items-start gap-1 rounded-lg border border-line-strong bg-card p-1.5 shadow-xl shadow-black/40">
      <IconButton title={replacing ? "Hide replace" : "Show replace"} onClick={() => setReplacing(!replacing)}>
        <ChevronRight className={cx("size-4 transition-transform", replacing && "rotate-90")} />
      </IconButton>
      <div className="w-80 space-y-1">
        <div className="flex items-center gap-1">
          <div className={cx("flex min-w-0 flex-1 items-center rounded-md border bg-card-2 pr-0.5", invalid ? "border-bad" : "border-line focus-within:border-accent")}>
            <input
              main-field="true"
              className={field}
              placeholder="Find"
              value={q.search}
              spellCheck={false}
              onChange={(e) => set({ search: e.target.value })}
              onKeyDown={(e) => keys(e, () => findNext(view))}
            />
            <IconButton title="Match case" active={q.caseSensitive} onClick={() => set({ caseSensitive: !q.caseSensitive })}><CaseSensitive className="size-4" /></IconButton>
            <IconButton title="Match whole word" active={q.wholeWord} onClick={() => set({ wholeWord: !q.wholeWord })}><WholeWord className="size-4" /></IconButton>
            <IconButton title="Use regular expression" active={q.regexp} onClick={() => set({ regexp: !q.regexp })}><Regex className="size-4" /></IconButton>
          </div>
          <span className={cx("w-[4.5rem] shrink-0 text-center text-xs tabular-nums", q.search && !total ? "text-bad" : "text-muted")}>
            {!q.search ? "" : invalid ? "Invalid" : total ? (current ? `${current} of ${total >= MAX_COUNT ? `${MAX_COUNT}+` : total}` : `${total >= MAX_COUNT ? `${MAX_COUNT}+` : total} found`) : "No results"}
          </span>
          <IconButton title="Previous match (Shift+Enter)" disabled={!total} onClick={() => findPrevious(view)}><ArrowUp className="size-4" /></IconButton>
          <IconButton title="Next match (Enter)" disabled={!total} onClick={() => findNext(view)}><ArrowDown className="size-4" /></IconButton>
          <IconButton title="Close (Escape)" onClick={close}><X className="size-4" /></IconButton>
        </div>
        {replacing && (
          <div className="flex items-center gap-1">
            <div className="flex min-w-0 flex-1 items-center rounded-md border border-line bg-card-2 focus-within:border-accent">
              <input
                className={field}
                placeholder="Replace"
                value={q.replace}
                spellCheck={false}
                disabled={view.state.readOnly}
                onChange={(e) => set({ replace: e.target.value })}
                onKeyDown={(e) => keys(e, () => replaceNext(view))}
              />
            </div>
            <IconButton title="Replace (Enter)" disabled={!total || view.state.readOnly} onClick={() => replaceNext(view)}><Replace className="size-4" /></IconButton>
            <IconButton title="Replace all" disabled={!total || view.state.readOnly} onClick={() => replaceAll(view)}><ReplaceAll className="size-4" /></IconButton>
            <span className="w-[4.5rem] shrink-0" />
          </div>
        )}
      </div>
    </div>
  );
}

/** Ctrl+F in the editor opens this instead of CodeMirror's default search bar. */
export const findWidget = [
  search({
    top: true,
    createPanel: (view): Panel => {
      const dom = document.createElement("div");
      const root = createRoot(dom);
      const draw = () => flushSync(() => root.render(<Find view={view} />));
      return {
        dom,
        top: true,
        mount: () => {
          draw();
          const input = dom.querySelector<HTMLInputElement>("[main-field]");
          input?.focus();
          input?.select();
        },
        update: (u: ViewUpdate) => {
          if (u.docChanged || u.selectionSet || u.transactions.some((t) => t.effects.some((e) => e.is(setSearchQuery)))) {
            const input = dom.querySelector<HTMLInputElement>("[main-field]");
            // Text set from outside the box (Ctrl+F takes the editor's selection): select it, like VS Code.
            // While typing, the field already holds the new text and keeps its cursor.
            const fromOutside = !!input && input.value !== getSearchQuery(u.state).search;
            queueMicrotask(() => {          // never render inside CodeMirror's own update cycle
              draw();
              if (fromOutside && input === document.activeElement) input.select();
            });
          }
        },
        destroy: () => queueMicrotask(() => root.unmount()),
      };
    },
  }),
  EditorView.theme({
    // Float the box at the top right of the editor, over the text (like VS Code).
    ".cm-panels.cm-panels-top": {
      position: "absolute", top: "8px", right: "18px", left: "auto",
      backgroundColor: "transparent", border: "none", zIndex: "20",
    },
    ".cm-searchMatch": { backgroundColor: "color-mix(in srgb, var(--accent) 22%, transparent)", borderRadius: "2px" },
    ".cm-searchMatch-selected, .cm-searchMatch.cm-searchMatch-selected": {
      backgroundColor: "color-mix(in srgb, var(--accent) 50%, transparent)",
      outline: "1px solid var(--accent)",
    },
  }),
];
