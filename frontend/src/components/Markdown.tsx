/* Safe markdown rendering: marked → DOMPurify → React.
 * Code blocks get hover copy buttons. */

import { useEffect, useMemo, useRef } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";

marked.setOptions({ breaks: true, gfm: true });

// open links in new tabs safely
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noreferrer noopener");
  }
});

export default function Markdown({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);

  const html = useMemo(() => {
    const raw = marked.parse(text || "", { async: false }) as string;
    return DOMPurify.sanitize(raw, {
      USE_PROFILES: { html: true },
      FORBID_TAGS: ["style", "form", "input", "iframe", "script"],
      FORBID_ATTR: ["style", "onerror", "onload"],
    });
  }, [text]);

  // attach copy buttons to code blocks
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    root.querySelectorAll("pre").forEach((pre) => {
      if (pre.querySelector(".code-copy")) return;
      const btn = document.createElement("button");
      btn.className = "code-copy";
      btn.textContent = "Copy";
      btn.addEventListener("click", () => {
        navigator.clipboard?.writeText(pre.querySelector("code")?.textContent || "");
        btn.textContent = "Copied";
        setTimeout(() => (btn.textContent = "Copy"), 1400);
      });
      pre.appendChild(btn);
    });
  }, [html]);

  return <div ref={ref} className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}
