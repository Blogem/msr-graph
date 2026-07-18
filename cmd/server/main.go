// Command server runs the msr-graph HTTP API. Only the /healthz endpoint is
// wired up here; the chat/review/checkpoint APIs and the embedded frontend
// are added by later tasks.
package main

import (
	"log"
	"net/http"
	"os"
)

func main() {
	addr := os.Getenv("SERVER_ADDR")
	if addr == "" {
		addr = ":8080"
	}

	log.Printf("server listening on %s", addr)
	if err := http.ListenAndServe(addr, newMux()); err != nil {
		log.Fatal(err)
	}
}
