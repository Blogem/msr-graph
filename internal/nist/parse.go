package nist

import (
	"bytes"
	"encoding/csv"
	"fmt"
	"io"
	"os"
)

// nistHeaderMarker is the exact prefix of the 13-column header line each
// vendored NIST file carries after its title + blank line. We locate it by
// substring search rather than counting lines, since the CSV rows below it
// may themselves span multiple physical lines (quoted comment fields
// containing embedded newlines).
const nistHeaderMarker = "Salt,Composition range"

// nistColumns is the fixed column count of a genuine NIST data row. Some of
// the vendored files carry a trailing free-text documentation block after
// the real data (itself parsed by encoding/csv as one or more short/long
// records); rows that don't have exactly this many columns are not data
// rows and are skipped.
const nistColumns = 13

// rawRow is one raw (uninterpreted) NIST CSV data row.
type rawRow struct {
	Salt              string
	CompositionRange  string
	DataType          string
	TMin              string
	TMax              string
	Uncertainty       string
	Data1             string
	Data2             string
	Data3             string
	Data4             string
	Data5             string
	Comment           string
	FormattingComment string
}

// propertyFile pairs a vendored file name with the property it carries.
type propertyFile struct {
	Name     string
	Property string
}

// propertyFiles is the fixed manifest of the four vendored NIST property
// files, in the order Process reports them.
var propertyFiles = []propertyFile{
	{Name: "density-csv.txt", Property: PropDensity},
	{Name: "viscosity-csv.txt", Property: PropViscosity},
	{Name: "s-tension-csv.txt", Property: PropSurfaceTension},
	{Name: "conductivity-csv.txt", Property: PropElectricalConductivity},
}

// parseFile reads one vendored NIST property file and returns its data rows.
// It skips the title + blank line preamble, uses encoding/csv (not naive
// line splitting) to correctly handle comment fields that carry embedded
// commas, quotes, and newlines, and drops any trailing non-data content
// (documentation footers) that doesn't have exactly nistColumns fields.
func parseFile(path string) ([]rawRow, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("nist: reading %s: %w", path, err)
	}

	idx := bytes.Index(content, []byte(nistHeaderMarker))
	if idx < 0 {
		return nil, fmt.Errorf("nist: %s: header row starting %q not found", path, nistHeaderMarker)
	}

	r := csv.NewReader(bytes.NewReader(content[idx:]))
	r.FieldsPerRecord = -1
	r.LazyQuotes = true

	if _, err := r.Read(); err != nil {
		return nil, fmt.Errorf("nist: %s: reading header row: %w", path, err)
	}

	var rows []rawRow
	for {
		record, err := r.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("nist: %s: %w", path, err)
		}
		if len(record) != nistColumns {
			// Not a genuine data row (e.g. a trailing documentation block);
			// skip it rather than fail the whole file.
			continue
		}
		rows = append(rows, rawRow{
			Salt:              record[0],
			CompositionRange:  record[1],
			DataType:          record[2],
			TMin:              record[3],
			TMax:              record[4],
			Uncertainty:       record[5],
			Data1:             record[6],
			Data2:             record[7],
			Data3:             record[8],
			Data4:             record[9],
			Data5:             record[10],
			Comment:           record[11],
			FormattingComment: record[12],
		})
	}
	return rows, nil
}
