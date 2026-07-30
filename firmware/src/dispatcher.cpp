#include "dispatcher.h"

#include <string.h>

#include "kivo_protocol.h"
#include "protocol_vocab.h"

void Dispatcher::handleLine(char* line) {
  kivo::ParsedFrame frame;
  kivo::ParseError err = kivo::parse_frame(line, frame);
  if (err == kivo::ParseError::CRC_FAIL) {
    io_.sendErrorEvent(KIVO_ERR_CRC_FAIL, KIVO_ERRMSG_CRC_FAIL);
    return;
  }
  if (err == kivo::ParseError::MALFORMED) {
    io_.sendErrorEvent(KIVO_ERR_MALFORMED, KIVO_ERRMSG_MALFORMED);
    return;
  }

  // The device only acts on commands; it ignores stray RES/EVT frames.
  if (frame.type != kivo::FrameType::CMD) {
    return;
  }

  // Split the body into "op" and "args". body points into the mutable line
  // buffer, so we can terminate the op in place.
  char* op = const_cast<char*>(frame.body);
  char* args = const_cast<char*>("");
  char* space = strchr(op, ' ');
  if (space != nullptr) {
    *space = '\0';
    args = space + 1;
  }

  for (size_t i = 0; i < count_; ++i) {
    if (strcmp(op, handlers_[i].op) == 0) {
      handlers_[i].fn(io_, frame.id, args);
      return;
    }
  }
  io_.sendError(frame.id, KIVO_ERR_UNKNOWN_OP, KIVO_ERRMSG_UNKNOWN_OP);
}
