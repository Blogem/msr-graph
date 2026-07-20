package graph

import (
	"fmt"
	"regexp"
	"strings"
)

// shaclNS is the SHACL vocabulary namespace. RDF4J/GraphDB validation
// reports use the sh: prefix in practice, but a predicate can legally be
// serialized as the full IRI too, so field detection matches both forms.
const shaclNS = "http://www.w3.org/ns/shacl#"

// Violation is one SHACL constraint violation extracted from an
// RDF4J/GraphDB validation report (an sh:ValidationResult). Fields are
// populated on a best-effort basis via string/regex extraction (this
// package does not parse RDF): any field that could not be found in the
// report body is left as the empty string rather than causing extraction
// to fail outright.
type Violation struct {
	// FocusNode is the sh:focusNode of the violated result -- the
	// offending subject/individual.
	FocusNode string
	// SourceConstraintComponent is the sh:sourceConstraintComponent that
	// rejected the write (e.g. sh:MinCountConstraintComponent).
	SourceConstraintComponent string
	// SourceShape is the sh:sourceShape that declared the constraint.
	SourceShape string
	// ResultPath is the sh:resultPath the violation was found on, if any.
	ResultPath string
	// Message is the sh:resultMessage, if the report carried one.
	Message string
}

// ValidationError indicates a graph write (Client.Update or
// Client.PutGraph) was rejected by SHACL validation rather than failing
// for a transport/generic reason. Callers distinguish it from other write
// failures via errors.As(err, &ve) with var ve *graph.ValidationError.
type ValidationError struct {
	// Violations are the individual constraint violations parsed out of
	// Report, one per sh:ValidationResult found. May be empty if the
	// report's markers were present but no individual result could be
	// parsed -- Report is always populated in that case so no detail is
	// lost.
	Violations []Violation
	// Report is the raw validation-report response body, kept verbatim
	// for cases where the caller wants to inspect what parsing missed.
	Report string
}

// Error renders a legible summary: the number of violations and, for
// each, whatever subset of focus node / constraint / shape / path /
// message could be extracted. This is deliberately more actionable than
// a bare HTTP status, per the "validation reports are legible to
// writers" requirement.
func (e *ValidationError) Error() string {
	if len(e.Violations) == 0 {
		return "graph: write rejected by SHACL validation (report carried no parseable sh:ValidationResult detail):\n" + e.Report
	}

	var b strings.Builder
	fmt.Fprintf(&b, "graph: write rejected by SHACL validation (%d violation(s)):", len(e.Violations))
	for _, v := range e.Violations {
		b.WriteString("\n  -")
		writeDetail(&b, " focusNode=", v.FocusNode)
		writeDetail(&b, " constraint=", v.SourceConstraintComponent)
		writeDetail(&b, " shape=", v.SourceShape)
		writeDetail(&b, " path=", v.ResultPath)
		writeDetail(&b, " message=", v.Message)
	}
	return b.String()
}

func writeDetail(b *strings.Builder, label, value string) {
	if value == "" {
		return
	}
	b.WriteString(label)
	b.WriteString(value)
}

// predicateAlt builds a regexp alternation matching a SHACL predicate in
// either its short (sh:local) or full-IRI (<http://.../shacl#local>)
// serialized form.
func predicateAlt(local string) string {
	return `(?:sh:` + local + `|<` + regexp.QuoteMeta(shaclNS+local) + `>)`
}

// fieldPattern holds the precompiled forms tried, in order, to extract
// the object of one SHACL predicate from a chunk of report text: an IRI
// ref, a triple-quoted string, a plain quoted string, and finally a bare
// token (a prefixed name like sh:MinCountConstraintComponent, or a
// blank-node/other identifier).
type fieldPattern struct {
	iri    *regexp.Regexp
	triple *regexp.Regexp
	quoted *regexp.Regexp
	bare   *regexp.Regexp
}

func newFieldPattern(local string) fieldPattern {
	alt := predicateAlt(local)
	return fieldPattern{
		iri:    regexp.MustCompile(alt + `\s+<([^>]*)>`),
		triple: regexp.MustCompile(alt + `\s+"""((?:[^\\]|\\.)*?)"""`),
		quoted: regexp.MustCompile(alt + `\s+"((?:[^"\\]|\\.)*)"`),
		bare:   regexp.MustCompile(alt + `\s+([A-Za-z][\w:.\-]*)`),
	}
}

// extract returns the first extracted value among the IRI, triple-quoted,
// quoted, and bare forms, or "" if the predicate is absent from chunk.
func (fp fieldPattern) extract(chunk string) string {
	for _, re := range []*regexp.Regexp{fp.iri, fp.triple, fp.quoted, fp.bare} {
		if m := re.FindStringSubmatch(chunk); m != nil {
			return strings.TrimRight(m[1], " \t\r\n.,;")
		}
	}
	return ""
}

var (
	focusNodeField    = newFieldPattern("focusNode")
	constraintField   = newFieldPattern("sourceConstraintComponent")
	sourceShapeField  = newFieldPattern("sourceShape")
	resultPathField   = newFieldPattern("resultPath")
	resultMessageFld  = newFieldPattern("resultMessage")
	focusNodeAnchorRe = regexp.MustCompile(predicateAlt("focusNode"))

	// validationReportMarker matches the report's own type declaration
	// (sh:ValidationReport / the full-IRI equivalent), which every
	// RDF4J/GraphDB rejection response carries.
	validationReportMarker = regexp.MustCompile(`(?i)ValidationReport`)
	// shaclResultMarker matches at least one field that only appears on
	// an actual sh:ValidationResult, so a body that merely mentions
	// "ValidationReport" in prose (rather than carrying one) is not
	// misclassified.
	shaclResultMarker = regexp.MustCompile(
		predicateAlt("focusNode") + `|` +
			predicateAlt("sourceConstraintComponent") + `|` +
			predicateAlt("resultMessage") + `|` +
			`(?i)ValidationResult`,
	)
)

// looksLikeValidationReport reports whether body appears to carry an
// RDF4J/GraphDB SHACL validation report: it must mention
// sh:ValidationReport together with at least one field that only occurs
// on an sh:ValidationResult. Both are required so an unrelated 5xx body
// that happens to mention "validation" in passing is not misclassified.
func looksLikeValidationReport(body []byte) bool {
	return validationReportMarker.Match(body) && shaclResultMarker.Match(body)
}

// parseViolations extracts one Violation per sh:ValidationResult found in
// report. Every SHACL validation result carries sh:focusNode, so results
// are split into chunks anchored on that predicate's occurrences; each
// chunk is scanned independently for the other fields. If report carries
// no sh:focusNode occurrence at all (report is present but nothing could
// be split out), it returns nil -- the caller still returns a
// *ValidationError, just with an empty Violations slice and the raw
// Report intact.
func parseViolations(report string) []Violation {
	locs := focusNodeAnchorRe.FindAllStringIndex(report, -1)
	if len(locs) == 0 {
		return nil
	}

	violations := make([]Violation, 0, len(locs))
	for i, loc := range locs {
		end := len(report)
		if i+1 < len(locs) {
			end = locs[i+1][0]
		}
		chunk := report[loc[0]:end]
		violations = append(violations, Violation{
			FocusNode:                 focusNodeField.extract(chunk),
			SourceConstraintComponent: constraintField.extract(chunk),
			SourceShape:               sourceShapeField.extract(chunk),
			ResultPath:                resultPathField.extract(chunk),
			Message:                   resultMessageFld.extract(chunk),
		})
	}
	return violations
}

// detectValidationError inspects a non-2xx write response body and, if it
// carries a SHACL validation report, returns a *ValidationError describing
// the rejection. It returns nil when body does not look like a validation
// report, so callers (Client.Update, Client.PutGraph) fall back to their
// existing generic error behavior unchanged.
func detectValidationError(body []byte) *ValidationError {
	if !looksLikeValidationReport(body) {
		return nil
	}
	return &ValidationError{
		Violations: parseViolations(string(body)),
		Report:     string(body),
	}
}
