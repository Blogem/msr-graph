package checkpoint_test

// Unit test for checkpoint.ValidateLabel (task 4.4, design D8): pure
// string validation, no filesystem or GraphDB needed, always runs.
//
// Pinned contract: checkpoint.ValidateLabel(label string) error validates
// {label} against "a conservative filesystem-safe charset" before any path
// is touched, rejecting path traversal, returning checkpoint.ErrInvalidLabel
// (detectable via errors.Is) on rejection.

import (
	"errors"
	"testing"

	"github.com/blogem/msr-graph/internal/checkpoint"
)

func TestValidateLabel(t *testing.T) {
	tests := []struct {
		name    string
		label   string
		wantErr bool
	}{
		{name: "simple alphanumeric label is accepted", label: "demo"},
		{name: "trailing numeric suffix is accepted", label: "demo-1"},
		{name: "underscore is accepted", label: "my_label"},
		{name: "empty label is rejected", label: "", wantErr: true},
		{name: "path traversal segment is rejected", label: "../etc", wantErr: true},
		{name: "path separator is rejected", label: "a/b", wantErr: true},
		{name: "dot is rejected", label: "a.b", wantErr: true},
		{name: "embedded whitespace is rejected", label: "has space", wantErr: true},
		{name: "bare dot-dot is rejected", label: "..", wantErr: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := checkpoint.ValidateLabel(tt.label)
			if !tt.wantErr {
				if err != nil {
					t.Fatalf("ValidateLabel(%q) = %v, want nil", tt.label, err)
				}
				return
			}
			if !errors.Is(err, checkpoint.ErrInvalidLabel) {
				t.Fatalf("ValidateLabel(%q) = %v, want errors.Is(err, checkpoint.ErrInvalidLabel)", tt.label, err)
			}
		})
	}
}
