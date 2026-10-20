import { useEffect, useRef } from "react";
import { basicSetup, EditorView } from "codemirror";
import { EditorState, Prec, type Extension } from "@codemirror/state";
import { keymap } from "@codemirror/view";
import { StreamLanguage } from "@codemirror/language";
import { properties } from "@codemirror/legacy-modes/mode/properties";
import { MySQL, sql } from "@codemirror/lang-sql";
import { oneDark } from "@codemirror/theme-one-dark";
import { MergeView } from "@codemirror/merge";
import { findWidget } from "./FindWidget";

type Lang = "conf" | "sql";

function language(lang: Lang): Extension {
  return lang === "sql" ? sql({ dialect: MySQL }) : StreamLanguage.define(properties);
}

const base = EditorView.theme({
  "&": { height: "100%", backgroundColor: "transparent" },
  ".cm-gutters": { backgroundColor: "transparent", borderRight: "1px solid var(--line)" },
});

interface Props {
  value: string;
  lang: Lang;
  onChange?: (value: string) => void;
  onSave?: () => void;
  onRun?: () => void;
  readOnly?: boolean;
}

/** CodeMirror 6 editor. `value` is applied when it changes from outside (file switch / reload). */
export function CodeEditor({ value, lang, onChange, onSave, onRun, readOnly }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const handlers = useRef({ onChange, onSave, onRun });
  handlers.current = { onChange, onSave, onRun };

  useEffect(() => {
    const keys = Prec.highest(
      keymap.of([
        { key: "Mod-s", preventDefault: true, run: () => (handlers.current.onSave?.(), true) },
        { key: "Mod-Enter", preventDefault: true, run: () => (handlers.current.onRun?.(), true) },
      ]),
    );
    view.current = new EditorView({
      parent: host.current!,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          keys,
          language(lang),
          base,
          oneDark,
          findWidget,
          EditorState.readOnly.of(!!readOnly),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) handlers.current.onChange?.(u.state.doc.toString());
          }),
        ],
      }),
    });
    return () => view.current?.destroy();
    // The editor is created once per language; content updates go through the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang, readOnly]);

  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== value) {
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
    }
  }, [value]);

  return <div ref={host} className="h-full min-h-0 overflow-hidden" />;
}

/** Side-by-side diff (read-only) used before saving a config file. */
export function DiffView({ original, modified }: { original: string; modified: string }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const common = [basicSetup, StreamLanguage.define(properties), EditorState.readOnly.of(true), EditorView.editable.of(false), oneDark, findWidget];
    const merge = new MergeView({
      parent: host.current!,
      a: { doc: original, extensions: common },
      b: { doc: modified, extensions: common },
      collapseUnchanged: { margin: 3, minSize: 6 },
      gutter: true,
    });
    return () => merge.destroy();
  }, [original, modified]);
  return <div ref={host} className="max-h-[60vh] overflow-auto rounded-lg border border-line text-xs" />;
}
