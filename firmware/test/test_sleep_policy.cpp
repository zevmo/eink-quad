#include <stdio.h>
#include <stdlib.h>

#include "../src/sleep_policy.h"

static int fails = 0;

static void expect(const char *name, uint32_t got, uint32_t want) {
  if (got != want) {
    printf("FAIL %s got %u want %u\n", name, got, want);
    fails++;
  }
}

int main() {
  // Old server: X-Next 0, or a 25s long-poll. Clock not set yet.
  expect("unsynced old", quad_sleep_seconds(0, 0, 0, 1), 300);
  expect("unsynced 25", quad_sleep_seconds(100, 0, 25, 1), 300);
  expect("unsynced 600", quad_sleep_seconds(100, 0, 600, 1), 600);

  // 1_700_000_100 is an exact 300s boundary.
  const int64_t slot = 1700000100LL;
  expect("on slot", quad_sleep_seconds(slot, slot, 0, 1), 300);
  // 20s of radio work after an on-time wake. Next check is still the next slot.
  expect("aligned remainder", quad_sleep_seconds(slot + 20, slot, 0, 1), 280);
  expect("old server aligned", quad_sleep_seconds(slot + 20, slot, 0, 1), 280);
  expect("live header ignored", quad_sleep_seconds(slot + 20, slot, 25, 1), 280);

  // Button is not an automatic check. The following automatic slot stays put.
  expect("after button", quad_sleep_seconds(slot + 240, slot, 300, 0), 60);

  // A slow automatic wake must not spin into the boundary 10s away.
  expect("no spin", quad_sleep_seconds(slot + 290, slot + 290, 0, 1), 310);

  expect("fail1", quad_fail_sleep(1), 300);
  expect("fail2", quad_fail_sleep(2), 600);
  expect("fail cap", quad_fail_sleep(40), 3600);

  if (quad_sleep_seconds(slot + 20, slot, 25, 1) < 300 &&
      quad_sleep_seconds(slot + 20, slot, 25, 1) == 25) {
    printf("FAIL regressed to 25\n");
    fails++;
  }
  if (fails) {
    printf("%d failed\n", fails);
    return 1;
  }
  printf("sleep policy ok\n");
  return 0;
}
