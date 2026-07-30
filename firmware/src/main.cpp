// Kivo firmware entry point.
//
// Wiring diagram of the software: bytes arrive on the serial line, are assembled
// into lines (SerialLine), parsed and routed by operation (Dispatcher) to a
// handler (handlers.cpp), which replies via ProtocolIO. The loop is cooperative
// and never blocks, so future capabilities (sensors, animations) can be serviced
// alongside command handling.

#include <Arduino.h>
#include <stdio.h>

#include "config.h"
#include "dispatcher.h"
#include "handlers.h"
#include "kivo_protocol.h"
#include "protocol_io.h"
#include "protocol_vocab.h"
#include "serial_line.h"

static SerialLine g_line;
static ProtocolIO g_io(g_line);
static Dispatcher g_dispatcher(g_io, KIVO_HANDLERS, KIVO_HANDLER_COUNT);

void setup() {
  g_line.begin(KIVO_BAUD);

  // Announce ourselves so the host can detect a fresh boot / unexpected reset
  // without polling (see /protocol/README.md §6).
  char identity[kivo::KIVO_LINE_MAX];
  snprintf(identity, sizeof(identity), "%s %s %s", KIVO_FW_NAME, KIVO_FW_VERSION,
           KIVO_PROTO_VERSION);
  g_io.sendEvent(KIVO_EVT_READY, identity);
}

void loop() {
  char* line = g_line.poll();
  if (line != nullptr) {
    g_dispatcher.handleLine(line);
  } else if (g_line.takeOverflow()) {
    // An over-long line was discarded; report it as a frame-level failure.
    g_io.sendErrorEvent(KIVO_ERR_MALFORMED, KIVO_ERRMSG_MALFORMED);
  }
}
