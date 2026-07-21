// Tests for the markdown-rendering helper (frontend-design-system /
// chat-ui spec "Assistant answers render sanitized markdown"; task 5.1),
// written against the pinned `$lib/markdown.ts` contract:
//   renderMarkdown(markdown: string): string
// -- parses with `marked` and sanitizes with `DOMPurify` (task 2.1),
// tolerant of incomplete/streamed input (chat-ui spec scenario "Incomplete
// streamed markdown does not break rendering").
//
// NOTE (pass 1): $lib/markdown.ts does not exist yet -- it is built
// concurrently by the wave chat-ui/foundation coder in a separate
// worktree. This suite is written directly against the pinned contract
// and the chat-ui spec's acceptance scenarios; it is expected to fail to
// resolve/compile until the merge, and is reconciled in pass 2.
import { describe, expect, it } from 'vitest';
import { renderMarkdown } from './markdown';

describe('renderMarkdown', () => {
	it('renders **bold** as <strong>', () => {
		const html = renderMarkdown('this is **bold** text');
		expect(html).toContain('<strong>bold</strong>');
	});

	it('renders a `- ` list as <li>', () => {
		const html = renderMarkdown('- first\n- second\n');
		expect(html).toContain('<li>');
		expect(html).toContain('first');
		expect(html).toContain('second');
	});

	it('renders inline code as <code>', () => {
		const html = renderMarkdown('use `renderMarkdown()` to render');
		expect(html).toContain('<code>');
		expect(html).toContain('renderMarkdown()');
	});

	it('renders a fenced code block as <pre>/<code>', () => {
		const html = renderMarkdown('```\nconst x = 1;\n```');
		expect(html).toContain('<pre>');
		expect(html).toContain('<code>');
		expect(html).toContain('const x = 1;');
	});

	it('renders a GFM table as <table>', () => {
		const table = ['| a | b |', '| --- | --- |', '| 1 | 2 |'].join('\n');
		const html = renderMarkdown(table);
		expect(html).toContain('<table>');
	});

	it('renders a link as <a href>', () => {
		const html = renderMarkdown('[NIST](https://www.nist.gov)');
		expect(html).toContain('<a');
		expect(html).toContain('href="https://www.nist.gov"');
	});

	it('strips an embedded <script> tag (XSS)', () => {
		const html = renderMarkdown('safe text <script>alert(1)</script> more text');
		expect(html).not.toContain('<script');
		expect(html).not.toContain('alert(1)');
	});

	it('strips an onerror= attribute (XSS)', () => {
		const html = renderMarkdown('<img src="x" onerror="alert(1)">');
		expect(html).not.toContain('onerror');
	});

	it('does not throw on an unterminated code fence and returns a string', () => {
		expect(() => renderMarkdown('partial answer with an unclosed fence:\n```\nconst x = ')).not.toThrow();
		const html = renderMarkdown('partial answer with an unclosed fence:\n```\nconst x = ');
		expect(typeof html).toBe('string');
		expect(html.length).toBeGreaterThan(0);
	});

	it('does not throw on other unterminated/partial markdown constructs', () => {
		expect(() => renderMarkdown('an unclosed **bold and an [unterminated link(')).not.toThrow();
		expect(() => renderMarkdown('')).not.toThrow();
	});
});
