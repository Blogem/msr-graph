package agent

import "strings"

// thinkOpen and thinkClose are the reasoning delimiters some
// OpenAI-compatible reasoning models inline into a message's content
// (e.g. "<think>step one...</think>the answer"). Matching is
// case-insensitive; splitReasoning lowercases a scan copy so the source
// text itself is preserved verbatim in the outputs.
const (
	thinkOpen  = "<think>"
	thinkClose = "</think>"
)

// splitReasoning separates any inline chain-of-thought from an assistant
// message's content. It removes every <think>...</think> block from
// content and returns (clean, reasoning): clean is the content with all
// blocks stripped and surrounding whitespace collapsed to a trimmed
// answer; reasoning is the concatenation of every block's inner text
// (blocks joined by a blank line), also trimmed.
//
// It tolerates the shapes a real stream produces: multiple blocks, a
// block with no answer text around it, and an unclosed <think> (the
// model or stream was cut off mid-reasoning) -- in which case everything
// after the dangling open tag is treated as reasoning. Tags are matched
// case-insensitively. When content has no reasoning at all, clean is the
// original content unchanged (aside from the trim) and reasoning is "".
func splitReasoning(content string) (clean, reasoning string) {
	lower := strings.ToLower(content)
	if !strings.Contains(lower, thinkOpen) {
		return strings.TrimSpace(content), ""
	}

	var answer strings.Builder
	var think []string
	for {
		open := strings.Index(lower, thinkOpen)
		if open < 0 {
			answer.WriteString(content)
			break
		}
		// Text before the open tag is answer content.
		answer.WriteString(content[:open])

		rest := content[open+len(thinkOpen):]
		lowerRest := lower[open+len(thinkOpen):]
		close := strings.Index(lowerRest, thinkClose)
		if close < 0 {
			// Unclosed block: the remainder is all reasoning.
			think = append(think, strings.TrimSpace(rest))
			content = ""
			break
		}
		think = append(think, strings.TrimSpace(rest[:close]))
		// Continue scanning after the close tag.
		content = rest[close+len(thinkClose):]
		lower = lowerRest[close+len(thinkClose):]
	}

	return strings.TrimSpace(answer.String()), strings.TrimSpace(strings.Join(think, "\n\n"))
}
