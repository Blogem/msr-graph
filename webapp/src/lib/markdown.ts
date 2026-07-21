// Single sanitize boundary for assistant markdown (chat-ui spec "Assistant
// answers render sanitized markdown"; design D2). Assistant `content` is
// untrusted LLM output: it is parsed with `marked` then always passed
// through `DOMPurify.sanitize()` before this function returns. No other
// module may produce HTML from assistant text — every render path goes
// through `renderMarkdown`.
import { marked } from 'marked';
import DOMPurify from 'dompurify';

/** Escapes the five HTML-significant characters so raw text can be safely
 * interpolated into an HTML string. Used only as the parse-failure fallback
 * below, so a chunk of markdown that fails to parse (should not happen in
 * practice, but streaming can hand `marked` pathological partial input)
 * still renders as inert text instead of throwing or leaking raw HTML. */
function escapeHtml(text: string): string {
	return text
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#39;');
}

/**
 * Parses `markdown` with `marked` and sanitizes the result with `DOMPurify`
 * before returning it, so the caller can hand the output straight to
 * Svelte's `{@html}`. Tolerant of incomplete/streamed input (e.g. an
 * unclosed code fence): parsing is wrapped in try/catch and any failure
 * falls back to the escaped raw text rather than throwing, so a partially
 * streamed answer never breaks rendering mid-stream.
 */
export function renderMarkdown(markdown: string): string {
	let html: string;
	try {
		// `async: false` pins marked's synchronous parse form (v18 can
		// return a Promise<string> in async mode) so this function always
		// returns a plain string.
		html = marked.parse(markdown, { async: false });
	} catch {
		return escapeHtml(markdown);
	}
	return DOMPurify.sanitize(html);
}
