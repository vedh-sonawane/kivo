// Kivo firmware entry point.
//
// Software wiring: bytes arrive on the serial line, are assembled into lines
// (SerialLine), parsed and routed by operation (Dispatcher) to a handler, which
// replies via ProtocolIO and actuates hardware via the DeviceContext. The loop
// is cooperative and never blocks, so sensors are serviced alongside command
// handling. All device internals live in kivo.h / kivo.cpp.

#include <Arduino.h>
#include <stdio.h>

#include "config.h"
#include "kivo.h"
#include "kivo_protocol.h"

static SerialLine g_line;
static ProtocolIO g_io(g_line);
static LcdDisplay g_display(KIVO_LCD_PIN_RS, KIVO_LCD_PIN_EN, KIVO_LCD_PIN_D4,
                            KIVO_LCD_PIN_D5, KIVO_LCD_PIN_D6, KIVO_LCD_PIN_D7,
                            KIVO_LCD_COLS, KIVO_LCD_ROWS);
static SensorManager g_sensors(KIVO_SENSORS, KIVO_SENSOR_COUNT, g_io,
                               KIVO_SENSOR_SAMPLE_MS);
static RgbLed g_led(KIVO_LED_PIN_R, KIVO_LED_PIN_G, KIVO_LED_PIN_B,
                    KIVO_LED_ACTIVE_LOW);
static Buzzer g_buzzer(KIVO_BUZZER_PIN);
static ServoArm g_servo(KIVO_SERVO_PIN);
static Button g_button(KIVO_BUTTON_PIN, g_io);
static DeviceContext g_ctx{g_io, g_display, g_sensors, g_led, g_buzzer, g_servo};
static Dispatcher g_dispatcher(g_ctx, KIVO_HANDLERS, KIVO_HANDLER_COUNT);

void setup() {
  g_line.begin(KIVO_BAUD);
  g_display.begin();
  g_sensors.begin();  // configure sensor pins (e.g. the PIR/ultrasonic pins)
  g_led.begin();      // LED off until the brain sets a mood colour
  g_buzzer.begin();
  g_servo.begin();    // centre the servo, "looking at you"
  g_button.begin();

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

  // Service subscribed sensors on their own cadence (non-blocking).
  g_sensors.poll(millis());
  // Poll the button every loop so short taps aren't missed.
  g_button.poll(millis());
}
