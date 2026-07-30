// Kivo firmware entry point.
//
// Wiring diagram of the software: bytes arrive on the serial line, are assembled
// into lines (SerialLine), parsed and routed by operation (Dispatcher) to a
// handler (handlers.cpp), which replies via ProtocolIO and actuates hardware via
// the DeviceContext. The loop is cooperative and never blocks, so future
// capabilities (sensors, animations) can be serviced alongside command handling.

#include <Arduino.h>
#include <stdio.h>

#include "config.h"
#include "device_context.h"
#include "dispatcher.h"
#include "handlers.h"
#include "kivo_protocol.h"
#include "lcd_display.h"
#include "protocol_io.h"
#include "protocol_vocab.h"
#include "serial_line.h"

static SerialLine g_line;
static ProtocolIO g_io(g_line);
static LcdDisplay g_display(KIVO_LCD_PIN_RS, KIVO_LCD_PIN_EN, KIVO_LCD_PIN_D4,
                            KIVO_LCD_PIN_D5, KIVO_LCD_PIN_D6, KIVO_LCD_PIN_D7,
                            KIVO_LCD_COLS, KIVO_LCD_ROWS);
static DeviceContext g_ctx{g_io, g_display};
static Dispatcher g_dispatcher(g_ctx, KIVO_HANDLERS, KIVO_HANDLER_COUNT);

void setup() {
  g_line.begin(KIVO_BAUD);
  g_display.begin();

  // A boot banner both confirms the LCD wiring at power-up and shows identity.
  g_display.clear();
  g_display.write(0, 0, KIVO_FW_NAME " v" KIVO_FW_VERSION);
  g_display.write(1, 0, "ready");

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
