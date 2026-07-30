// Services a command handler may use, passed to it by the dispatcher.
//
// A plain struct of references, not a global grab-bag: handlers receive exactly
// this and nothing more, which keeps them decoupled from how the device is
// assembled in main.cpp. Adding a peripheral means adding one field here and
// constructing it in main; handlers that don't need it simply ignore it.

#ifndef KIVO_DEVICE_CONTEXT_H
#define KIVO_DEVICE_CONTEXT_H

#include "lcd_display.h"
#include "protocol_io.h"

struct DeviceContext {
  ProtocolIO& io;
  LcdDisplay& display;
};

#endif  // KIVO_DEVICE_CONTEXT_H
