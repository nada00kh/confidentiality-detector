// WASHQ frontend settings.
// USE_MOCK false (default): the pages call the local FastAPI backend at API_BASE (see backend/README.md).
// USE_MOCK true: demo data from js/mock.js, a few browser patterns only, not the real detector.
// CHECK_TIMEOUT_MS: how long a scan may take before it is stopped and shown as failed (never as a result).
// 60 s: the slowest scan measured on a laptop CPU at the 10,000-character limit took about 11 s (2026-10-30),
// so this leaves room for slower computers and for one scan waiting behind another.
window.WASHQ_CONFIG = {
  USE_MOCK: false,
  API_BASE: "http://localhost:8000",
  CHECK_TIMEOUT_MS: 60000,
  MOCK_DELAY_MS: 900
};
