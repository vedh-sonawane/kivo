#include "handlers.h"

#include <stdio.h>
#include <stdlib.h>

#include "config.h"
#include "kivo_protocol.h"
#include "protocol_vocab.h"

// -- core / handshake --------------------------------------------------------

void handlePing(DeviceContext& ctx, uint16_t id, const char* args) {
  (void)args;
  ctx.io.sendOk(id, KIVO_PAYLOAD_PONG);
}

void handleIdentify(DeviceContext& ctx, uint16_t id, const char* args) {
  (void)args;
  char identity[kivo::KIVO_LINE_MAX];
  snprintf(identity, sizeof(identity), "%s %s %s", KIVO_FW_NAME, KIVO_FW_VERSION,
           KIVO_PROTO_VERSION);
  ctx.io.sendOk(id, identity);
}

// -- display -----------------------------------------------------------------

// Parse "<row> <col> <text>". On success writes row/col/text and returns true.
// `args` is not modified; `text` points into it.
static bool parseWriteArgs(const char* args, long& row, long& col,
                           const char*& text) {
  char* end = nullptr;
  row = strtol(args, &end, 10);
  if (end == args || *end != ' ') return false;

  const char* after_row = end + 1;
  col = strtol(after_row, &end, 10);
  if (end == after_row) return false;

  if (*end == ' ') {
    text = end + 1;
  } else if (*end == '\0') {
    text = "";  // positioning with no text is a valid no-op write
  } else {
    return false;  // trailing garbage where a space or end was expected
  }
  return true;
}

void handleDisplayWrite(DeviceContext& ctx, uint16_t id, const char* args) {
  long row = 0;
  long col = 0;
  const char* text = "";
  if (!parseWriteArgs(args, row, col, text) || row < 0 || col < 0) {
    ctx.io.sendError(id, KIVO_ERR_BAD_ARGS, KIVO_ERRMSG_BAD_ARGS);
    return;
  }
  // The driver bounds-checks against the actual geometry and reports if the
  // cell is off-screen; the host never needs to know the dimensions.
  if (!ctx.display.write(static_cast<uint8_t>(row), static_cast<uint8_t>(col),
                         text)) {
    ctx.io.sendError(id, KIVO_ERR_BAD_ARGS, KIVO_ERRMSG_BAD_ARGS);
    return;
  }
  ctx.io.sendOk(id);
}

void handleDisplayClear(DeviceContext& ctx, uint16_t id, const char* args) {
  (void)args;
  ctx.display.clear();
  ctx.io.sendOk(id);
}

// Operation names are matched exactly and are case-sensitive (uppercase by
// convention). Keep this table the single source of registered capabilities.
const CommandHandler KIVO_HANDLERS[] = {
    {"PING", handlePing},
    {"SYS.IDENTIFY", handleIdentify},
    {"DISPLAY.WRITE", handleDisplayWrite},
    {"DISPLAY.CLEAR", handleDisplayClear},
};

const size_t KIVO_HANDLER_COUNT = sizeof(KIVO_HANDLERS) / sizeof(KIVO_HANDLERS[0]);
