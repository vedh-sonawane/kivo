#include "handlers.h"

#include <stdio.h>

#include "config.h"
#include "kivo_protocol.h"
#include "protocol_vocab.h"

void handlePing(ProtocolIO& io, uint16_t id, const char* args) {
  (void)args;
  io.sendOk(id, KIVO_PAYLOAD_PONG);
}

void handleIdentify(ProtocolIO& io, uint16_t id, const char* args) {
  (void)args;
  char identity[kivo::KIVO_LINE_MAX];
  snprintf(identity, sizeof(identity), "%s %s %s", KIVO_FW_NAME, KIVO_FW_VERSION,
           KIVO_PROTO_VERSION);
  io.sendOk(id, identity);
}

// Operation names are matched exactly and are case-sensitive (uppercase by
// convention). Keep this table the single source of registered capabilities.
const CommandHandler KIVO_HANDLERS[] = {
    {"PING", handlePing},
    {"SYS.IDENTIFY", handleIdentify},
};

const size_t KIVO_HANDLER_COUNT = sizeof(KIVO_HANDLERS) / sizeof(KIVO_HANDLERS[0]);
