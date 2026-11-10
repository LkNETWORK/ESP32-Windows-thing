// Pure gesture classification, imported by app.js and the Node tests.

export const GESTURE_DEFAULTS = Object.freeze({
  tapMaxMs: 300,
  tapMaxMove: 12,
  swipeMin: 50,
  axisRatio: 1.2,
});

export function clamp01(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(1, number));
}

export function volumeDelta(direction, step = 0.05) {
  if (direction === "up") return step;
  if (direction === "down") return -step;
  return 0;
}

/**
 * Classify one pointer sequence.
 *
 * samples: [{x, y, t}, ...] where t is a monotonic millisecond timestamp.
 * Returns {type, dx, dy, duration}. type is one of:
 * tap, swipe_left, swipe_right, swipe_up, swipe_down, none.
 */
export function classifyGesture(samples, options = GESTURE_DEFAULTS) {
  const opts = { ...GESTURE_DEFAULTS, ...(options || {}) };
  if (!Array.isArray(samples) || samples.length < 2) {
    return { type: "none", dx: 0, dy: 0, duration: 0 };
  }

  const start = samples[0];
  const end = samples[samples.length - 1];
  if (
    !Number.isFinite(start.x) ||
    !Number.isFinite(start.y) ||
    !Number.isFinite(start.t) ||
    !Number.isFinite(end.x) ||
    !Number.isFinite(end.y) ||
    !Number.isFinite(end.t)
  ) {
    return { type: "none", dx: 0, dy: 0, duration: 0 };
  }

  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const duration = Math.max(0, end.t - start.t);
  const absX = Math.abs(dx);
  const absY = Math.abs(dy);

  if (absX <= opts.tapMaxMove && absY <= opts.tapMaxMove && duration <= opts.tapMaxMs) {
    return { type: "tap", dx, dy, duration };
  }

  if (absX >= opts.swipeMin && absX >= absY * opts.axisRatio) {
    return { type: dx < 0 ? "swipe_left" : "swipe_right", dx, dy, duration };
  }

  if (absY >= opts.swipeMin && absY >= absX * opts.axisRatio) {
    return { type: dy < 0 ? "swipe_up" : "swipe_down", dx, dy, duration };
  }

  return { type: "none", dx, dy, duration };
}
