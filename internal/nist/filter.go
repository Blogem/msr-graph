package nist

import (
	"regexp"
	"strings"
)

// fluorideComponentRe matches a single hyphen-split formula token that is a
// fluoride of one of the cations in scope: Li, Be, Na, K, Zr, U, Th.
var fluorideComponentRe = regexp.MustCompile(`^(Li|Be|Na|K|Zr|U|Th)F[0-9]?$`)

// IsFluoride reports whether every hyphen component of saltToken is a
// fluoride of a cation in {Li, Be, Na, K, Zr, U, Th}. A well-formed but
// out-of-scope salt (chloride, mixed-anion, or any other cation) returns
// false; the caller (Process) counts that as out-of-scope, not flagged.
func IsFluoride(saltToken string) bool {
	components := strings.Split(strings.TrimSpace(saltToken), "-")
	if len(components) == 0 {
		return false
	}
	for _, c := range components {
		if !fluorideComponentRe.MatchString(strings.TrimSpace(c)) {
			return false
		}
	}
	return true
}
