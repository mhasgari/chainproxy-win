// Command chainlantern runs the Lantern client backend (github.com/getlantern/radiance) headless
// for Chain Proxy: free-plan servers, automatic best-server selection, and a local SOCKS5/HTTP
// (mixed) inbound instead of a TUN device - no admin rights, no system service, no IPC pipe.
//
// It is built INSIDE a checkout of radiance (see dev/build_lantern.py) with the `novpn` tag, and
// is therefore licensed GPL-3.0-or-later like radiance. Chain Proxy itself only starts it as a
// separate program and reads its stdout.
//
// Protocol (stdout, one line each): "CHAINLANTERN READY <addr>" once connected, then
// "CHAINLANTERN STATUS <connected|connecting|...>" every few seconds, "CHAINLANTERN ERROR <text>".
// The program exits when its stdin is closed (the parent died) or on SIGINT/SIGTERM.
package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/getlantern/radiance/backend"
	commonenv "github.com/getlantern/radiance/common/env"
	"github.com/getlantern/radiance/vpn"
)

func say(format string, a ...any) {
	fmt.Printf("CHAINLANTERN "+format+"\n", a...)
}

func main() {
	dataPath := flag.String("data-path", "", "directory for Lantern's state (required)")
	logPath := flag.String("log-path", "", "directory for Lantern's logs (default: data-path/log)")
	logLevel := flag.String("log-level", "info", "trace, debug, info, warn, error")
	listen := flag.String("listen", "127.0.0.1:18080", "SOCKS5/HTTP listen address (loopback only)")
	tag := flag.String("tag", vpn.AutoSelectTag, "server tag, default: automatic best server")
	flag.Parse()
	if *dataPath == "" {
		say("ERROR --data-path is required")
		os.Exit(2)
	}
	if *logPath == "" {
		*logPath = *dataPath + string(os.PathSeparator) + "log"
	}
	for _, d := range []string{*dataPath, *logPath} {
		if err := os.MkdirAll(d, 0o700); err != nil {
			say("ERROR cannot create %s: %v", d, err)
			os.Exit(1)
		}
	}
	os.Setenv(commonenv.SocksAddress.String(), *listen)
	os.Setenv(commonenv.DisableStdout.String(), "true")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { // the parent closes our stdin (or dies): shut down, never linger as an orphan
		io.Copy(io.Discard, os.Stdin)
		cancel()
	}()
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	go func() { <-sig; cancel() }()

	be, err := backend.NewLocalBackend(ctx, backend.Options{
		DataDir:                  *dataPath,
		LogDir:                   *logPath,
		LogLevel:                 *logLevel,
		PreserveTelemetryConsent: true,
	})
	if err != nil {
		say("ERROR backend: %v", err)
		os.Exit(1)
	}
	defer be.Close()
	if user, err := be.UserData(); err == nil && user == nil {
		if _, err := be.NewUser(ctx); err != nil {
			say("ERROR new anonymous user: %v", err)
		}
	}
	be.Start()

	go func() { // keep trying until connected; the config fetch needs the network to be up
		for ctx.Err() == nil {
			err := be.ConnectVPN(ctx, *tag)
			if err == nil {
				say("READY %s", *listen)
				return
			}
			say("ERROR connect: %v", err)
			select {
			case <-ctx.Done():
			case <-time.After(5 * time.Second):
			}
		}
	}()

	tick := time.NewTicker(3 * time.Second)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			say("STATUS stopping")
			return
		case <-tick.C:
			say("STATUS %s", be.VPNStatus())
		}
	}
}
