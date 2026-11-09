#pragma once
// Host-testable. No Arduino includes.
//
// Automatic checks are never closer than 5 minutes. A button wake is not an
// automatic check and is not passed through here. 25-second long-polls are
// not a legal answer, including when an old server sends X-Mode live and
// X-Next 0.
#include <stdint.h>

static const uint32_t QUAD_POLL_FLOOR_S = 300;
static const uint32_t QUAD_SLEEP_MAX_S = 900;
static const int64_t QUAD_TIME_VALID = 1700000000LL;

// now / lastAuto are unix seconds. lastAuto is the start of the previous
// automatic wake, or 0. thisWakeWasAuto is 1 when this wake is the timer
// or a cold boot, not a button. serverNext is the X-Next header (0 if the
// server didn't send one).
inline uint32_t quad_sleep_seconds(int64_t now, int64_t lastAuto,
                                   uint32_t serverNext, int thisWakeWasAuto) {
  uint32_t hinted = serverNext;
  if (hinted < QUAD_POLL_FLOOR_S || hinted > QUAD_SLEEP_MAX_S)
    hinted = QUAD_POLL_FLOOR_S;

  if (now < QUAD_TIME_VALID)
    return hinted;

  int64_t next = now - (now % 300) + 300;
  if (thisWakeWasAuto && (next - now) < 60)
    next += 300;
  if (lastAuto >= QUAD_TIME_VALID) {
    int64_t earliest = lastAuto + (int64_t)QUAD_POLL_FLOOR_S;
    if (next < earliest) {
      next = earliest;
      int64_t rem = next % 300;
      if (rem) next += 300 - rem;
    }
  }
  if (serverNext > QUAD_POLL_FLOOR_S && serverNext <= QUAD_SLEEP_MAX_S) {
    int64_t later = now + (int64_t)serverNext;
    if (later > next) {
      next = later;
      int64_t rem = next % 300;
      if (rem) next += 300 - rem;
    }
  }
  int64_t sec = next - now;
  if (sec < 60) sec += 300;
  if (sec > (int64_t)QUAD_SLEEP_MAX_S) sec = QUAD_SLEEP_MAX_S;
  return (uint32_t)sec;
}

// Wi-Fi or HTTP failure. Never the old 60-second ladder, and never 25 seconds.
inline uint32_t quad_fail_sleep(uint32_t failures) {
  uint32_t n = failures < 1 ? 1 : failures;
  uint64_t s = (uint64_t)QUAD_POLL_FLOOR_S * n;
  if (s > 3600) s = 3600;
  return (uint32_t)s;
}
