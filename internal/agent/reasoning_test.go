package agent

import "testing"

func TestSplitReasoning(t *testing.T) {
	cases := []struct {
		name          string
		content       string
		wantClean     string
		wantReasoning string
	}{
		{
			name:      "no reasoning",
			content:   "The density is 1.94 g/cm^3.",
			wantClean: "The density is 1.94 g/cm^3.",
		},
		{
			name:          "single inline block before answer",
			content:       "<think>let me compute this</think>The density is 1.94.",
			wantClean:     "The density is 1.94.",
			wantReasoning: "let me compute this",
		},
		{
			name:          "block surrounded by answer text",
			content:       "Prefix <think>hidden</think>suffix",
			wantClean:     "Prefix suffix",
			wantReasoning: "hidden",
		},
		{
			name:          "multiple blocks joined",
			content:       "a<think>r1</think>b<think>r2</think>c",
			wantClean:     "abc",
			wantReasoning: "r1\n\nr2",
		},
		{
			name:          "unclosed block is all reasoning",
			content:       "answer so far<think>reasoning cut off",
			wantClean:     "answer so far",
			wantReasoning: "reasoning cut off",
		},
		{
			name:          "only reasoning, no answer",
			content:       "<think>just thinking</think>",
			wantClean:     "",
			wantReasoning: "just thinking",
		},
		{
			name:          "case-insensitive tags",
			content:       "<THINK>upper</THINK>done",
			wantClean:     "done",
			wantReasoning: "upper",
		},
		{
			name:      "empty content",
			content:   "",
			wantClean: "",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			gotClean, gotReasoning := splitReasoning(tc.content)
			if gotClean != tc.wantClean {
				t.Errorf("clean = %q, want %q", gotClean, tc.wantClean)
			}
			if gotReasoning != tc.wantReasoning {
				t.Errorf("reasoning = %q, want %q", gotReasoning, tc.wantReasoning)
			}
		})
	}
}
