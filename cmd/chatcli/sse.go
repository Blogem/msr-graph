package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"strings"
)

// ParseSSE reads a Server-Sent Events stream from r and invokes handle
// once per event, in order. It implements the subset of the SSE wire
// format cmd/server/sse.go produces (event: <type>\ndata: <json>\n\n)
// plus the general SSE convention it builds on: consecutive "data:"
// lines accumulate, joined by "\n", until a blank line terminates the
// event and the accumulated data is JSON-decoded. Lines starting with
// ":" are comments and ignored; an "event:" line is tolerated but not
// relied on, since the JSON payload itself carries a "type"
// discriminator. A stream that ends without a trailing blank line still
// flushes its last event.
func ParseSSE(r io.Reader, handle func(Event)) error {
	scanner := bufio.NewScanner(r)
	// Trace payloads (tool results, script stdout) can be large; grow the
	// scanner's buffer well past bufio's 64KiB default line limit.
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)

	var dataLines []string
	flush := func() error {
		if len(dataLines) == 0 {
			return nil
		}
		data := strings.Join(dataLines, "\n")
		dataLines = nil

		var ev Event
		if err := json.Unmarshal([]byte(data), &ev); err != nil {
			return fmt.Errorf("decode SSE event data %q: %w", data, err)
		}
		handle(ev)
		return nil
	}

	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			if err := flush(); err != nil {
				return err
			}
			continue
		}
		if strings.HasPrefix(line, ":") {
			continue
		}

		field, value := splitSSEField(line)
		switch field {
		case "data":
			dataLines = append(dataLines, value)
		case "event", "id", "retry":
			// Not used: the JSON payload's "type" field is the
			// authoritative discriminator.
		}
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("read SSE stream: %w", err)
	}

	return flush()
}

// splitSSEField splits an SSE field line ("field: value" or
// "field:value") into its field name and value, per the SSE spec's
// leading-single-space convention. A line with no colon is a
// field name with an empty value.
func splitSSEField(line string) (field, value string) {
	idx := strings.Index(line, ":")
	if idx == -1 {
		return line, ""
	}
	field = line[:idx]
	value = line[idx+1:]
	value = strings.TrimPrefix(value, " ")
	return field, value
}
