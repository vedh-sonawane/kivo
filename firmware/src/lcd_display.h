// A narrow display capability backed by the Arduino LiquidCrystal library.
//
// The vendor library is a private implementation detail: callers depend only on
// this small API (begin / clear / write). Pins and geometry are injected via the
// constructor (from config.h) rather than baked in, so the wiring lives in one
// place and a differently-wired or differently-sized character LCD needs no code
// change here. If a non-HD44780 display is ever added, extract an abstract base
// from this class at that point — not before.

#ifndef KIVO_LCD_DISPLAY_H
#define KIVO_LCD_DISPLAY_H

#include <LiquidCrystal.h>
#include <stdint.h>

class LcdDisplay {
 public:
  LcdDisplay(uint8_t rs, uint8_t en, uint8_t d4, uint8_t d5, uint8_t d6,
             uint8_t d7, uint8_t cols, uint8_t rows);

  // Initialize the hardware. Call once from setup().
  void begin();

  // Clear the entire screen.
  void clear();

  // Write text starting at (row, col). Text is truncated at the right edge of
  // the row. Returns false (writing nothing) if row/col are out of range.
  bool write(uint8_t row, uint8_t col, const char* text);

  uint8_t cols() const { return cols_; }
  uint8_t rows() const { return rows_; }

 private:
  LiquidCrystal lcd_;
  uint8_t cols_;
  uint8_t rows_;
};

#endif  // KIVO_LCD_DISPLAY_H
