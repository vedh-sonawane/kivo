// Command handlers and the registry the dispatcher iterates over.
//
// To add a capability: implement a handler here (and its driver, once hardware
// is involved) and add one row to KIVO_HANDLERS in handlers.cpp.

#ifndef KIVO_HANDLERS_H
#define KIVO_HANDLERS_H

#include "dispatcher.h"

// Core / handshake.
void handlePing(DeviceContext& ctx, uint16_t id, const char* args);
void handleIdentify(DeviceContext& ctx, uint16_t id, const char* args);

// Display capability.
void handleDisplayWrite(DeviceContext& ctx, uint16_t id, const char* args);
void handleDisplayClear(DeviceContext& ctx, uint16_t id, const char* args);

// Registry consumed by main.cpp when constructing the Dispatcher.
extern const CommandHandler KIVO_HANDLERS[];
extern const size_t KIVO_HANDLER_COUNT;

#endif  // KIVO_HANDLERS_H
