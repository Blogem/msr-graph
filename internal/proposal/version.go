package proposal

import (
	"fmt"
	"strconv"
	"strings"
)

// BumpMinor parses version as "major.minor[.patch]" -- dropping any
// pre-release suffix such as chunk 7/8's "-seed" first -- increments
// minor, and resets patch to 0 (design D2): "0.4.0" -> "0.5.0",
// "0.4.0-seed" -> "0.5.0". It returns an error if version does not parse
// down to at least a numeric major and minor, so an unparseable stored
// value fails the approval loudly rather than writing a malformed
// version.
func BumpMinor(version string) (string, error) {
	v := version
	if i := strings.IndexByte(v, '-'); i >= 0 {
		v = v[:i]
	}
	if i := strings.IndexByte(v, '+'); i >= 0 {
		v = v[:i]
	}

	parts := strings.Split(v, ".")
	if len(parts) < 2 {
		return "", fmt.Errorf("proposal: version %q is not major.minor[.patch]", version)
	}

	major, err := strconv.Atoi(parts[0])
	if err != nil {
		return "", fmt.Errorf("proposal: version %q has a non-numeric major component: %w", version, err)
	}
	minor, err := strconv.Atoi(parts[1])
	if err != nil {
		return "", fmt.Errorf("proposal: version %q has a non-numeric minor component: %w", version, err)
	}

	return fmt.Sprintf("%d.%d.0", major, minor+1), nil
}
