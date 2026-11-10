import test from "node:test";
import assert from "node:assert/strict";

import {
  classifyGesture,
  clamp01,
  volumeDelta,
} from "../../companion/web/gestures.mjs";

const point = (x, y, t) => ({ x, y, t });

test("tap is a short, small movement", () => {
  const result = classifyGesture([point(100, 100, 0), point(104, 102, 120)]);
  assert.equal(result.type, "tap");
});

test("a long press is not a tap", () => {
  const result = classifyGesture([point(100, 100, 0), point(100, 100, 900)]);
  assert.equal(result.type, "none");
});

test("horizontal swipes change track", () => {
  const left = classifyGesture([point(300, 200, 0), point(180, 205, 260)]);
  const right = classifyGesture([point(180, 205, 0), point(300, 200, 260)]);
  assert.equal(left.type, "swipe_left");
  assert.equal(right.type, "swipe_right");
});

test("vertical swipes change volume", () => {
  const up = classifyGesture([point(200, 300, 0), point(204, 160, 260)]);
  const down = classifyGesture([point(200, 160, 0), point(196, 300, 260)]);
  assert.equal(up.type, "swipe_up");
  assert.equal(down.type, "swipe_down");
});

test("small movements are ignored", () => {
  const result = classifyGesture([point(200, 200, 0), point(220, 220, 200)]);
  assert.equal(result.type, "none");
});

test("ambiguous diagonals are ignored", () => {
  const result = classifyGesture([point(100, 100, 0), point(180, 170, 250)]);
  assert.equal(result.type, "none");
});

test("volume delta and clamp", () => {
  assert.equal(volumeDelta("up"), 0.05);
  assert.equal(volumeDelta("down"), -0.05);
  assert.equal(volumeDelta("left"), 0);
  assert.equal(clamp01(1.4), 1);
  assert.equal(clamp01(-0.2), 0);
  assert.equal(clamp01(Number.NaN), 0);
});
