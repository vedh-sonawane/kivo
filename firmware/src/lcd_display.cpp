#include "lcd_display.h"

LcdDisplay::LcdDisplay(uint8_t rs, uint8_t en, uint8_t d4, uint8_t d5, uint8_t d6,
                       uint8_t d7, uint8_t cols, uint8_t rows)
    : lcd_(rs, en, d4, d5, d6, d7), cols_(cols), rows_(rows) {}

void LcdDisplay::begin() { lcd_.begin(cols_, rows_); }

void LcdDisplay::clear() { lcd_.clear(); }

bool LcdDisplay::write(uint8_t row, uint8_t col, const char* text) {
  if (row >= rows_ || col >= cols_) {
    return false;
  }
  lcd_.setCursor(col, row);
  // Print only what fits between col and the right edge, so text never spills
  // into off-screen DDRAM or the next line.
  uint8_t budget = cols_ - col;
  for (uint8_t i = 0; i < budget && text[i] != '\0'; ++i) {
    lcd_.write(text[i]);
  }
  return true;
}
