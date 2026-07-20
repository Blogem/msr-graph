package proposal_test

// Unit test for proposal.BumpMinor (task 3.6, design D2): pure
// string-in/string-out version parsing, no GraphDB needed, always runs.
//
// Pinned contract: proposal.BumpMinor(version string) (string, error)
// parses major.minor.patch (dropping any pre-release suffix such as
// "-seed"), increments the minor component, and resets patch to 0. The
// design.md "Risks" section explicitly states the parser "tolerates a
// missing patch" -- so a two-component input is expected to succeed with
// patch treated as 0 -- while a value it truly cannot parse "fails the
// approval loudly rather than writing a malformed version".

import (
	"testing"

	"github.com/blogem/msr-graph/internal/proposal"
)

func TestBumpMinor(t *testing.T) {
	tests := []struct {
		name    string
		in      string
		want    string
		wantErr bool
	}{
		{
			name: "seed baseline 0.4.0 bumps to 0.5.0 (pinned by proposal-lifecycle spec.md)",
			in:   "0.4.0",
			want: "0.5.0",
		},
		{
			name: "pre-release suffix -seed is dropped before bumping (pinned by proposal-lifecycle spec.md)",
			in:   "0.4.0-seed",
			want: "0.5.0",
		},
		{
			name: "0.3.0 bumps to 0.4.0",
			in:   "0.3.0",
			want: "0.4.0",
		},
		{
			name: "minor rollover only touches the minor component, not major",
			in:   "1.2.9",
			want: "1.3.0",
		},
		{
			name: "missing patch component is tolerated (design.md Risks: 'the parser tolerates a missing patch')",
			in:   "0.4",
			want: "0.5.0",
		},
		{
			name:    "unparseable version string is refused",
			in:      "not-a-version",
			wantErr: true,
		},
		{
			name:    "empty string is refused",
			in:      "",
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := proposal.BumpMinor(tt.in)
			if tt.wantErr {
				if err == nil {
					t.Fatalf("BumpMinor(%q) = %q, nil; want a non-nil error", tt.in, got)
				}
				return
			}
			if err != nil {
				t.Fatalf("BumpMinor(%q) returned unexpected error: %v", tt.in, err)
			}
			if got != tt.want {
				t.Errorf("BumpMinor(%q) = %q, want %q", tt.in, got, tt.want)
			}
		})
	}
}
