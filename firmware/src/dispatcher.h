// Routes a parsed command to the handler registered for its operation name.
//
// Adding a capability means writing a handler and adding one row to the
// registry (see handlers.cpp) — the dispatcher itself never changes.

#ifndef KIVO_DISPATCHER_H
#define KIVO_DISPATCHER_H

#include <stddef.h>
#include <stdint.h>

#include "protocol_io.h"

// A handler receives the correlation id and the argument string (everything
// after the operation name; empty if none). It replies via `io`.
typedef void (*HandlerFn)(ProtocolIO& io, uint16_t id, const char* args);

struct CommandHandler {
  const char* op;
  HandlerFn fn;
};

class Dispatcher {
 public:
  Dispatcher(ProtocolIO& io, const CommandHandler* handlers, size_t count)
      : io_(io), handlers_(handlers), count_(count) {}

  // Parse and act on one raw line (mutated in place by the parser).
  void handleLine(char* line);

 private:
  ProtocolIO& io_;
  const CommandHandler* handlers_;
  size_t count_;
};

#endif  // KIVO_DISPATCHER_H
